"""
Vehicle telemetry reporting to an OpenEVSE WiFi module.

Pushes the simulated vehicle's battery state to a real OpenEVSE over HTTP
(POST /status) and/or MQTT, so WiFi firmware features that consume vehicle
data - SoC display, Boost, charge limits - can be exercised without a car.

Both transports carry the same four values, named as the firmware names them:

    battery_level         SoC percentage
    battery_range         Driving range in km
    time_to_full_charge   Seconds until the charge limit is reached
    vehicle_charge_limit  The vehicle's own charge limit, as a percentage

IMPORTANT: the firmware only accepts vehicle data from the source selected by
its `vehicle_data_src` setting - 3 (HTTP) for the POST path, 2 (MQTT) for the
MQTT topics. Pushes from the other transport are parsed and silently dropped.
The HTTP path can detect this (see HttpTelemetryReporter.send); MQTT is
fire-and-forget with no acknowledgement, so a wrong setting there is invisible
from this side.
"""

import json
import threading
from typing import Optional
from urllib.parse import urlparse, urlunparse

# Fields sent to the firmware, in the firmware's own naming.
TELEMETRY_FIELDS = (
    "battery_level",
    "battery_range",
    "time_to_full_charge",
    "vehicle_charge_limit",
)

# Default MQTT topic suffixes, matching the OpenEVSE config option names
# (mqtt_vehicle_soc, mqtt_vehicle_range, mqtt_vehicle_eta, ...).
DEFAULT_MQTT_SUFFIXES = {
    "battery_level": "soc",
    "battery_range": "range",
    "time_to_full_charge": "eta",
    "vehicle_charge_limit": "charge_limit",
}

# The firmware echoes the posted document back, adding this key only when a
# vehicle field was actually accepted. Its absence means the push was dropped.
VEHICLE_ACCEPTED_KEY = "vehicle_state_update"

DEFAULT_INTERVAL_SEC = 30.0
DEFAULT_HTTP_TIMEOUT_SEC = 5.0
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_TOPIC_PREFIX = "emulator/vehicle"


def _require_number(value, name: str, minimum: Optional[float] = None) -> float:
    """
    Coerce a configured value to a number.

    Args:
        value: Configured value
        name: Setting name, for the error message
        minimum: If given, the value must be strictly greater than this

    Returns:
        The value as a float

    Raises:
        ValueError: If the value is not numeric, or not above minimum
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None

    if minimum is not None and number <= minimum:
        raise ValueError(f"{name} must be > {minimum:g}, got {number:g}")

    return number


def _require_bool(value, name: str) -> bool:
    """
    Check a configured value is a boolean.

    Rejecting is safer than coercing here: bool("false") is True, so a string
    would silently invert the setting rather than fail.

    Args:
        value: Configured value
        name: Setting name, for the error message

    Returns:
        The value

    Raises:
        ValueError: If the value is not a bool
    """
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false, got {value!r}")
    return value


def _require_text(value, name: str) -> str:
    """
    Check a configured value is a string.

    Args:
        value: Configured value
        name: Setting name, for the error message

    Returns:
        The value

    Raises:
        ValueError: If the value is not a string
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    return value


def _optional_text(value, name: str) -> Optional[str]:
    """
    Check a configured value is a string or None.

    Args:
        value: Configured value
        name: Setting name, for the error message

    Returns:
        The value

    Raises:
        ValueError: If the value is neither a string nor None
    """
    return None if value is None else _require_text(value, name)


def build_telemetry(ev) -> dict:
    """
    Read the current vehicle telemetry from an EV simulator.

    Args:
        ev: EVSimulator to read from

    Returns:
        Dict keyed by the firmware's field names
    """
    status = ev.get_status()
    return {
        "battery_level": round(status["soc"], 1),
        "battery_range": round(status["range_km"], 1),
        "time_to_full_charge": status["time_to_full_charge_sec"],
        "vehicle_charge_limit": int(round(status["charge_limit_soc"])),
    }


def status_url(url: str) -> str:
    """
    Resolve a configured URL to the OpenEVSE status endpoint.

    Accepts either a base URL ("http://openevse.local") or one that already
    names the endpoint ("http://openevse.local/status"), so a user who copies
    the full endpoint out of the docs is not silently posting to /status/status.

    Args:
        url: Base URL or full status endpoint URL

    Returns:
        The full status endpoint URL

    Raises:
        ValueError: If the URL is not a string, or has no scheme or host
    """
    _require_text(url, "reporting.http.url")

    parsed = urlparse(url if "://" in url else f"http://{url}")
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid OpenEVSE URL: {url!r}")

    path = parsed.path.rstrip("/")
    if not path.endswith("/status"):
        path = f"{path}/status"

    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


class HttpTelemetryReporter:
    """Pushes vehicle telemetry to an OpenEVSE via POST /status."""

    def __init__(
        self,
        url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout_sec: float = DEFAULT_HTTP_TIMEOUT_SEC,
    ):
        """
        Initialize the HTTP reporter.

        Args:
            url: OpenEVSE base URL or full /status URL
            username: Optional HTTP basic auth username
            password: Optional HTTP basic auth password
            timeout_sec: Per-request timeout in seconds

        Raises:
            ValueError: If url is empty or malformed, or any setting has the
                wrong type
        """
        if not url:
            raise ValueError("HTTP reporting requires a URL")

        self.url = status_url(url)
        username = _optional_text(username, "reporting.http.username")
        password = _optional_text(password, "reporting.http.password")
        # Both halves must be strings: requests deprecates None components, and
        # the firmware keys auth on the password anyway, substituting a default
        # admin user for a blank username.
        self.auth = (username or "", password or "") if username or password else None
        self.timeout_sec = _require_number(
            timeout_sec, "reporting.http.timeout_sec", minimum=0
        )

        self.last_error: Optional[str] = None
        # Latched so a misconfigured vehicle_data_src is reported once, not
        # once per interval for as long as the emulator runs.
        self._warned_rejected = False

    def send(self, telemetry: dict) -> bool:
        """
        Post telemetry to the OpenEVSE.

        Args:
            telemetry: Field dict from build_telemetry()

        Returns:
            True if the push was accepted by the firmware
        """
        # Imported lazily so the emulator still runs with reporting disabled
        # when the optional dependency is missing.
        import requests

        try:
            response = requests.post(
                self.url, json=telemetry, auth=self.auth, timeout=self.timeout_sec
            )
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"Vehicle telemetry HTTP push failed: {self.last_error}")
            return False

        if response.status_code == 401:
            self.last_error = (
                "401 Unauthorized (check reporting.http username/password)"
            )
            print(f"Vehicle telemetry HTTP push rejected: {self.last_error}")
            return False

        if response.status_code != 200:
            self.last_error = f"HTTP {response.status_code}"
            print(f"Vehicle telemetry HTTP push failed: {self.last_error}")
            return False

        if not self._accepted(response):
            self.last_error = (
                "OpenEVSE ignored the vehicle data; set its vehicle_data_src to "
                "3 (HTTP) to accept pushed telemetry"
            )
            if not self._warned_rejected:
                self._warned_rejected = True
                print(f"Vehicle telemetry HTTP push ignored: {self.last_error}")
            return False

        self.last_error = None
        self._warned_rejected = False
        return True

    def _accepted(self, response) -> bool:
        """
        Whether the firmware actually consumed the vehicle fields.

        The response echoes the posted document with VEHICLE_ACCEPTED_KEY added
        only when a vehicle field was applied. An unparseable body is treated as
        accepted: the 200 is the firmware's own answer, and guessing otherwise
        would raise a false alarm on a firmware that changes its reply.
        """
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return True

        return isinstance(body, dict) and VEHICLE_ACCEPTED_KEY in body


class MqttTelemetryReporter:
    """Publishes vehicle telemetry to an MQTT broker as scalar payloads."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_MQTT_PORT,
        username: Optional[str] = None,
        password: Optional[str] = None,
        topic_prefix: str = DEFAULT_MQTT_TOPIC_PREFIX,
        topics: Optional[dict] = None,
        retain: bool = True,
    ):
        """
        Initialize the MQTT reporter.

        Args:
            host: Broker hostname
            port: Broker port
            username: Optional broker username
            password: Optional broker password
            topic_prefix: Prefix for the default per-field topics
            topics: Optional per-field topic overrides, keyed by field name
            retain: Publish retained, so the OpenEVSE gets the last value on
                (re)subscribe rather than waiting a full interval

        Raises:
            ValueError: If host is empty, an override names an unknown field,
                or any setting has the wrong type
        """
        if not host:
            raise ValueError("MQTT reporting requires a broker host")

        overrides = topics or {}
        if not isinstance(overrides, dict):
            raise ValueError(
                f"reporting.mqtt.topics must be an object, got "
                f"{type(topics).__name__}"
            )

        unknown = set(overrides) - set(TELEMETRY_FIELDS)
        if unknown:
            raise ValueError(
                f"Unknown MQTT telemetry field(s): {', '.join(sorted(unknown))}"
            )

        for field, topic in overrides.items():
            _require_text(topic, f"reporting.mqtt.topics.{field}")

        self.host = _require_text(host, "reporting.mqtt.host")
        self.port = int(_require_number(port, "reporting.mqtt.port", minimum=0))
        self.username = _optional_text(username, "reporting.mqtt.username")
        self.password = _optional_text(password, "reporting.mqtt.password")
        self.retain = _require_bool(retain, "reporting.mqtt.retain")
        prefix = _require_text(topic_prefix, "reporting.mqtt.topic_prefix").rstrip("/")
        self.topics = {
            field: overrides.get(field, f"{prefix}/{DEFAULT_MQTT_SUFFIXES[field]}")
            for field in TELEMETRY_FIELDS
        }

        self.last_error: Optional[str] = None
        self._client = None

    def _connect(self):
        """Create and start the client, reusing a live one."""
        if self._client is not None:
            return self._client

        # Imported lazily so the emulator still runs with reporting disabled
        # when the optional dependency is missing.
        import paho.mqtt.client as mqtt

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self.username or self.password:
            client.username_pw_set(self.username, self.password)

        client.connect(self.host, self.port)
        # Runs the network loop on its own thread, which also gives us
        # automatic reconnection between intervals.
        client.loop_start()
        self._client = client
        return client

    def send(self, telemetry: dict) -> bool:
        """
        Publish each telemetry field to its topic.

        Args:
            telemetry: Field dict from build_telemetry()

        Returns:
            True if every field was published
        """
        import paho.mqtt.client as mqtt

        try:
            client = self._connect()
            for field, value in telemetry.items():
                info = client.publish(
                    self.topics[field], str(value), retain=self.retain
                )
                # publish() reports a dead connection through rc rather than
                # raising, so without this a disconnected broker looks like a
                # clean success - the exact silent failure this feature exists
                # to make visible.
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise RuntimeError(
                        f"publish to {self.topics[field]} failed: "
                        f"{mqtt.error_string(info.rc)}"
                    )
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"Vehicle telemetry MQTT publish failed: {self.last_error}")
            # Drop the client so the next interval reconnects from scratch
            # rather than reusing a half-dead one.
            self.close()
            return False

        self.last_error = None
        return True

    def close(self):
        """Stop the network loop and drop the client."""
        if self._client is None:
            return

        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as e:
            print(f"Warning: Could not close MQTT client: {e}")
        finally:
            self._client = None


class TelemetryReporter:
    """Periodically pushes vehicle telemetry over every enabled transport."""

    def __init__(
        self,
        ev,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
        http: Optional[HttpTelemetryReporter] = None,
        mqtt: Optional[MqttTelemetryReporter] = None,
    ):
        """
        Initialize the reporter.

        Args:
            ev: EVSimulator to read telemetry from
            interval_sec: Seconds between pushes
            http: Optional HTTP transport
            mqtt: Optional MQTT transport

        Raises:
            ValueError: If interval_sec is not a positive number
        """
        self.ev = ev
        self.interval_sec = _require_number(
            interval_sec, "reporting.interval_sec", minimum=0
        )
        self.http = http
        self.mqtt = mqtt

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_telemetry: Optional[dict] = None
        self._stop_event = threading.Event()

    @property
    def enabled(self) -> bool:
        """Whether any transport is configured."""
        return self.http is not None or self.mqtt is not None

    def start(self) -> bool:
        """
        Start periodic reporting.

        Returns:
            True if reporting is running, False if no transport is configured
            (which is the normal disabled case, not an error). Calling this on
            an already-running reporter is a no-op.
        """
        if not self.enabled:
            return False

        if self.thread is not None and self.thread.is_alive():
            # Starting again would leave the previous thread running and
            # publishing, doubling the push rate with no way to reach it.
            return True

        transports = []
        if self.http:
            transports.append(f"HTTP {self.http.url}")
        if self.mqtt:
            transports.append(f"MQTT {self.mqtt.host}:{self.mqtt.port}")
        print(
            f"Reporting vehicle telemetry every {self.interval_sec:g}s to: "
            f"{', '.join(transports)}"
        )

        self._stop_event.clear()
        self.running = True
        self.thread = threading.Thread(target=self._report_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        """Stop reporting and release the transports."""
        self.running = False
        self._stop_event.set()

        if self.thread:
            self.thread.join(timeout=2.0)
            # Only drop the reference once it has really stopped. An in-flight
            # HTTP push can outlast this join (its own timeout defaults to 5s),
            # and clearing regardless would hide a live thread from start(),
            # which would then run a second one alongside it.
            if not self.thread.is_alive():
                self.thread = None

        if self.mqtt:
            self.mqtt.close()

    def publish_once(self) -> dict:
        """
        Read the vehicle state and push it over every enabled transport.

        Returns:
            Dict with the telemetry sent and each transport's result
        """
        telemetry = build_telemetry(self.ev)
        self.last_telemetry = telemetry

        results = {}
        if self.http:
            results["http"] = self.http.send(telemetry)
        if self.mqtt:
            results["mqtt"] = self.mqtt.send(telemetry)

        return {"telemetry": telemetry, "results": results}

    def get_status(self) -> dict:
        """
        Get the reporter's current state.

        Returns:
            Dictionary describing the enabled transports and last push
        """
        status = {
            "enabled": self.enabled,
            "running": self.running,
            "interval_sec": self.interval_sec,
            "last_telemetry": self.last_telemetry,
            "http": None,
            "mqtt": None,
        }

        if self.http:
            status["http"] = {"url": self.http.url, "last_error": self.http.last_error}
        if self.mqtt:
            status["mqtt"] = {
                "host": self.mqtt.host,
                "port": self.mqtt.port,
                "topics": self.mqtt.topics,
                "last_error": self.mqtt.last_error,
            }

        return status

    def _report_loop(self):
        """Push telemetry on the configured interval until stopped."""
        # The stop event is authoritative as well as `running`: a set event must
        # end the loop, not just cut the wait short and spin.
        while self.running and not self._stop_event.is_set():
            try:
                self.publish_once()
            except Exception as e:
                # A reporting failure must never take down the emulator, so the
                # loop swallows anything the transports did not already handle.
                print(f"Vehicle telemetry push error: {e}")

            # Interruptible, so stop() does not wait out a long interval.
            self._stop_event.wait(self.interval_sec)


def build_reporter(ev, config: dict) -> TelemetryReporter:
    """
    Build a TelemetryReporter from the 'reporting' config section.

    Args:
        ev: EVSimulator to read telemetry from
        config: The 'reporting' config dict

    Returns:
        A TelemetryReporter, with no transports when reporting is disabled

    Raises:
        ValueError: If an enabled transport is misconfigured
    """
    http_config = config.get("http", {})
    mqtt_config = config.get("mqtt", {})

    http = None
    if _require_bool(http_config.get("enabled", False), "reporting.http.enabled"):
        http = HttpTelemetryReporter(
            url=http_config.get("url"),
            username=http_config.get("username"),
            password=http_config.get("password"),
            timeout_sec=http_config.get("timeout_sec", DEFAULT_HTTP_TIMEOUT_SEC),
        )

    mqtt = None
    if _require_bool(mqtt_config.get("enabled", False), "reporting.mqtt.enabled"):
        mqtt = MqttTelemetryReporter(
            host=mqtt_config.get("host"),
            port=mqtt_config.get("port", DEFAULT_MQTT_PORT),
            username=mqtt_config.get("username"),
            password=mqtt_config.get("password"),
            topic_prefix=mqtt_config.get("topic_prefix", DEFAULT_MQTT_TOPIC_PREFIX),
            topics=mqtt_config.get("topics"),
            retain=mqtt_config.get("retain", True),
        )

    return TelemetryReporter(
        ev,
        interval_sec=config.get("interval_sec", DEFAULT_INTERVAL_SEC),
        http=http,
        mqtt=mqtt,
    )

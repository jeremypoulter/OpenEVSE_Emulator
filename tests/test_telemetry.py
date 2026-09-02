"""Tests for vehicle telemetry reporting to an OpenEVSE."""

from unittest.mock import MagicMock, patch

import pytest

from src.emulator.ev import EVSimulator
from src.emulator.telemetry import (
    DEFAULT_MQTT_SUFFIXES,
    TELEMETRY_FIELDS,
    HttpTelemetryReporter,
    MqttTelemetryReporter,
    TelemetryReporter,
    build_reporter,
    build_telemetry,
    status_url,
)


def make_response(status_code=200, json_body=None, raises=False):
    """Build a stand-in for a requests Response."""
    response = MagicMock()
    response.status_code = status_code
    if raises:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


class TestStatusUrl:
    """URL resolution for the OpenEVSE status endpoint."""

    def test_appends_status_to_base_url(self):
        assert status_url("http://openevse.local") == "http://openevse.local/status"

    def test_does_not_double_up_existing_status_path(self):
        """A user pasting the full endpoint must not get /status/status."""
        assert (
            status_url("http://openevse.local/status") == "http://openevse.local/status"
        )

    def test_tolerates_trailing_slash(self):
        assert status_url("http://openevse.local/") == "http://openevse.local/status"

    def test_assumes_http_when_scheme_omitted(self):
        assert status_url("openevse.local") == "http://openevse.local/status"

    def test_preserves_https_and_port(self):
        assert status_url("https://evse:8443") == "https://evse:8443/status"

    def test_rejects_url_without_host(self):
        with pytest.raises(ValueError):
            status_url("http://")


class TestBuildTelemetry:
    """Telemetry is emitted under the firmware's own field names."""

    def test_uses_firmware_field_names(self):
        ev = EVSimulator()
        telemetry = build_telemetry(ev)
        assert set(telemetry) == set(TELEMETRY_FIELDS)

    def test_reports_soc_range_and_limit(self):
        ev = EVSimulator(range_km_at_full=400.0, charge_limit_soc=80.0)
        ev.soc = 50.0

        telemetry = build_telemetry(ev)

        assert telemetry["battery_level"] == 50.0
        assert telemetry["battery_range"] == 200.0
        assert telemetry["vehicle_charge_limit"] == 80

    def test_eta_is_zero_when_not_charging(self):
        """time_to_full_charge is meaningless with no charge in progress."""
        ev = EVSimulator()
        assert build_telemetry(ev)["time_to_full_charge"] == 0

    def test_eta_is_in_seconds(self):
        """The firmware stores the ETA in seconds, not hours."""
        ev = EVSimulator(battery_capacity_kwh=100.0)
        ev.soc = 50.0
        ev.connected = True
        ev.requesting_charge = True
        # 50 kWh remaining at 10 kW = 5 hours = 18000 seconds.
        ev.update_charging(offered_current_amps=0, voltage=0, delta_time_sec=0)
        with patch.object(EVSimulator, "_time_to_full_charge_sec", return_value=18000):
            assert build_telemetry(ev)["time_to_full_charge"] == 18000


class TestHttpTelemetryReporter:
    """HTTP push to POST /status."""

    def test_requires_a_url(self):
        with pytest.raises(ValueError):
            HttpTelemetryReporter(url="")

    def test_auth_omitted_when_no_credentials(self):
        assert HttpTelemetryReporter(url="http://evse").auth is None

    def test_auth_set_from_credentials(self):
        reporter = HttpTelemetryReporter(url="http://evse", username="u", password="p")
        assert reporter.auth == ("u", "p")

    def test_successful_push_posts_telemetry(self):
        reporter = HttpTelemetryReporter(url="http://evse")
        response = make_response(json_body={"vehicle_state_update": 0})

        with patch("requests.post", return_value=response) as mock_post:
            assert reporter.send({"battery_level": 42.0}) is True

        assert mock_post.call_args.args[0] == "http://evse/status"
        assert mock_post.call_args.kwargs["json"] == {"battery_level": 42.0}
        assert reporter.last_error is None

    def test_push_ignored_when_firmware_drops_vehicle_data(self):
        """
        A 200 without vehicle_state_update means the OpenEVSE parsed the body
        but discarded the vehicle fields, because vehicle_data_src is not HTTP.
        """
        reporter = HttpTelemetryReporter(url="http://evse")
        response = make_response(json_body={"battery_level": 42.0})

        with patch("requests.post", return_value=response):
            assert reporter.send({"battery_level": 42.0}) is False

        assert "vehicle_data_src" in reporter.last_error

    def test_rejection_is_only_warned_once(self):
        """The warning must not repeat on every interval."""
        reporter = HttpTelemetryReporter(url="http://evse")
        response = make_response(json_body={})

        with patch("requests.post", return_value=response):
            with patch("builtins.print") as mock_print:
                reporter.send({})
                reporter.send({})
                reporter.send({})

        assert mock_print.call_count == 1

    def test_unauthorized_is_reported_clearly(self):
        reporter = HttpTelemetryReporter(url="http://evse", username="u", password="p")

        with patch("requests.post", return_value=make_response(status_code=401)):
            assert reporter.send({}) is False

        assert "401" in reporter.last_error

    def test_http_error_status_is_a_failure(self):
        reporter = HttpTelemetryReporter(url="http://evse")

        with patch("requests.post", return_value=make_response(status_code=500)):
            assert reporter.send({}) is False

        assert "500" in reporter.last_error

    def test_connection_error_does_not_raise(self):
        """A missing OpenEVSE must not take down the emulator."""
        reporter = HttpTelemetryReporter(url="http://evse")

        with patch("requests.post", side_effect=OSError("unreachable")):
            assert reporter.send({}) is False

        assert "unreachable" in reporter.last_error

    def test_unparseable_body_is_treated_as_accepted(self):
        """A 200 is the firmware's answer; do not raise a false alarm on it."""
        reporter = HttpTelemetryReporter(url="http://evse")

        with patch("requests.post", return_value=make_response(raises=True)):
            assert reporter.send({}) is True


class TestMqttTelemetryReporter:
    """MQTT publishing of telemetry."""

    def test_requires_a_host(self):
        with pytest.raises(ValueError):
            MqttTelemetryReporter(host="")

    def test_default_topics_use_firmware_suffixes(self):
        reporter = MqttTelemetryReporter(host="broker", topic_prefix="car")
        for field, suffix in DEFAULT_MQTT_SUFFIXES.items():
            assert reporter.topics[field] == f"car/{suffix}"

    def test_trailing_slash_in_prefix_does_not_double_up(self):
        reporter = MqttTelemetryReporter(host="broker", topic_prefix="car/")
        assert reporter.topics["battery_level"] == "car/soc"

    def test_per_field_topic_override(self):
        reporter = MqttTelemetryReporter(
            host="broker", topics={"battery_level": "custom/soc"}
        )
        assert reporter.topics["battery_level"] == "custom/soc"
        # Un-overridden fields keep their defaults.
        assert reporter.topics["battery_range"].endswith("/range")

    def test_unknown_topic_override_is_rejected(self):
        """A typo in a topic key would otherwise publish nowhere, silently."""
        with pytest.raises(ValueError) as exc_info:
            MqttTelemetryReporter(host="broker", topics={"battery_lvl": "x"})
        assert "battery_lvl" in str(exc_info.value)

    def test_publishes_scalar_payloads(self):
        """The firmware parses payloads with toInt(), so they must be scalars."""
        reporter = MqttTelemetryReporter(host="broker", topic_prefix="car")
        client = MagicMock()

        with patch.object(reporter, "_connect", return_value=client):
            assert reporter.send({"battery_level": 42.0}) is True

        client.publish.assert_called_once_with("car/soc", "42.0", retain=True)

    def test_publish_failure_drops_the_client(self):
        """A half-dead client must not be reused on the next interval."""
        reporter = MqttTelemetryReporter(host="broker")
        client = MagicMock()
        client.publish.side_effect = OSError("broker gone")
        reporter._client = client

        with patch.object(reporter, "_connect", return_value=client):
            assert reporter.send({"battery_level": 1.0}) is False

        assert reporter._client is None
        assert "broker gone" in reporter.last_error

    def test_close_is_safe_without_a_client(self):
        MqttTelemetryReporter(host="broker").close()


class TestTelemetryReporter:
    """The orchestrating reporter."""

    def test_rejects_non_positive_interval(self):
        with pytest.raises(ValueError):
            TelemetryReporter(EVSimulator(), interval_sec=0)

    def test_disabled_without_transports(self):
        reporter = TelemetryReporter(EVSimulator())
        assert reporter.enabled is False
        assert reporter.start() is False
        assert reporter.running is False

    def test_publish_once_pushes_to_every_transport(self):
        http, mqtt = MagicMock(), MagicMock()
        http.send.return_value = True
        mqtt.send.return_value = False

        reporter = TelemetryReporter(EVSimulator(), http=http, mqtt=mqtt)
        result = reporter.publish_once()

        assert result["results"] == {"http": True, "mqtt": False}
        assert http.send.call_args.args[0] == result["telemetry"]
        assert mqtt.send.call_args.args[0] == result["telemetry"]

    def test_loop_survives_a_transport_raising(self):
        """A throwing transport must not kill the reporting thread."""
        http = MagicMock()
        reporter = TelemetryReporter(EVSimulator(), interval_sec=0.01, http=http)

        def explode(_telemetry):
            reporter._stop_event.set()  # Let exactly one pass run.
            raise RuntimeError("boom")

        http.send.side_effect = explode
        reporter.running = True

        # Returns rather than propagating: the thread would otherwise die.
        reporter._report_loop()

        assert http.send.call_count == 1

    def test_loop_exits_on_stop_event_without_spinning(self):
        """A set stop event must end the loop, not just cut the wait short."""
        http = MagicMock()
        reporter = TelemetryReporter(EVSimulator(), interval_sec=600, http=http)
        reporter.running = True
        reporter._stop_event.set()

        reporter._report_loop()

        assert http.send.call_count == 0

    def test_stop_closes_the_mqtt_client(self):
        mqtt = MagicMock()
        reporter = TelemetryReporter(EVSimulator(), mqtt=mqtt)
        reporter.stop()
        mqtt.close.assert_called_once()

    def test_status_reports_transports(self):
        reporter = TelemetryReporter(
            EVSimulator(),
            http=HttpTelemetryReporter(url="http://evse"),
            mqtt=MqttTelemetryReporter(host="broker"),
        )
        status = reporter.get_status()

        assert status["enabled"] is True
        assert status["http"]["url"] == "http://evse/status"
        assert status["mqtt"]["host"] == "broker"


class TestBuildReporter:
    """Construction from the 'reporting' config section."""

    def test_empty_config_yields_a_disabled_reporter(self):
        assert build_reporter(EVSimulator(), {}).enabled is False

    def test_transports_are_independent(self):
        """Either transport can be enabled without the other."""
        reporter = build_reporter(
            EVSimulator(),
            {"http": {"enabled": True, "url": "http://evse"}, "mqtt": {}},
        )
        assert reporter.http is not None
        assert reporter.mqtt is None

    def test_both_transports_can_be_enabled(self):
        reporter = build_reporter(
            EVSimulator(),
            {
                "interval_sec": 5,
                "http": {"enabled": True, "url": "http://evse"},
                "mqtt": {"enabled": True, "host": "broker"},
            },
        )
        assert reporter.http is not None
        assert reporter.mqtt is not None
        assert reporter.interval_sec == 5

    def test_enabled_http_without_url_is_an_error(self):
        with pytest.raises(ValueError):
            build_reporter(EVSimulator(), {"http": {"enabled": True}})

    def test_enabled_mqtt_without_host_is_an_error(self):
        with pytest.raises(ValueError):
            build_reporter(EVSimulator(), {"mqtt": {"enabled": True}})

    def test_disabled_transport_with_bad_config_is_ignored(self):
        """Leftover config for a disabled transport must not block startup."""
        reporter = build_reporter(
            EVSimulator(), {"http": {"enabled": False, "url": None}}
        )
        assert reporter.enabled is False


class TestHttpAuthCoercion:
    """Basic auth components must be strings, never None."""

    def test_password_only_sends_an_empty_username(self):
        reporter = HttpTelemetryReporter(url="http://evse", password="p")
        assert reporter.auth == ("", "p")

    def test_username_only_sends_an_empty_password(self):
        reporter = HttpTelemetryReporter(url="http://evse", username="u")
        assert reporter.auth == ("u", "")

    def test_no_credentials_means_no_auth(self):
        assert HttpTelemetryReporter(url="http://evse").auth is None


class TestConfigTypeValidation:
    """
    Wrong types must raise ValueError, not crash.

    Callers rely on that: startup disables reporting with a message, and
    POST /api/reporting/config returns a 400. Anything else surfaces as a
    traceback or a 500 instead of a usable error.
    """

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"url": 1234},
            {"url": ["http://evse"]},
            {"url": "http://evse", "timeout_sec": "soon"},
            {"url": "http://evse", "username": 1},
            {"url": "http://evse", "password": []},
        ],
    )
    def test_http_rejects_wrong_types(self, kwargs):
        with pytest.raises(ValueError):
            HttpTelemetryReporter(**kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"host": 42},
            {"host": "broker", "port": "soon"},
            {"host": "broker", "topics": 42},
            {"host": "broker", "topics": {"battery_level": 5}},
            {"host": "broker", "topic_prefix": 7},
            {"host": "broker", "username": 1},
        ],
    )
    def test_mqtt_rejects_wrong_types(self, kwargs):
        with pytest.raises(ValueError):
            MqttTelemetryReporter(**kwargs)

    @pytest.mark.parametrize("interval", ["fast", None, [], {}])
    def test_interval_rejects_wrong_types(self, interval):
        with pytest.raises(ValueError):
            TelemetryReporter(EVSimulator(), interval_sec=interval)

    def test_numeric_strings_are_accepted(self):
        """Config files and JSON bodies routinely carry numbers as strings."""
        reporter = TelemetryReporter(EVSimulator(), interval_sec="15")
        assert reporter.interval_sec == 15.0
        assert MqttTelemetryReporter(host="broker", port="8883").port == 8883

    def test_error_names_the_setting(self):
        """The message has to say which setting, not just that one is wrong."""
        with pytest.raises(ValueError) as exc_info:
            MqttTelemetryReporter(host="broker", topic_prefix=7)
        assert "reporting.mqtt.topic_prefix" in str(exc_info.value)

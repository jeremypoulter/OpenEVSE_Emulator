"""
Flask web API for controlling the emulator.

Provides REST endpoints and WebSocket interface.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
import os
from typing import TYPE_CHECKING, Optional

# Handle imports for both direct execution and test execution
try:
    from emulator.evse import ErrorFlags
    from emulator.config import merge_config
    from emulator.telemetry import build_reporter
except ImportError:
    # When imported as src.web.api from tests
    from ..emulator.evse import ErrorFlags
    from ..emulator.config import merge_config
    from ..emulator.telemetry import build_reporter

if TYPE_CHECKING:
    try:
        from emulator.evse import EVSEStateMachine
        from emulator.ev import EVSimulator
    except ImportError:
        from ..emulator.evse import EVSEStateMachine
        from ..emulator.ev import EVSimulator


# Keys accepted by POST /api/reporting/config, mirroring the 'reporting' config
# section. Checked explicitly because merge_config would otherwise fold a typo
# into the stored config, where it would sit looking applied and doing nothing.
REPORTING_SECTION_KEYS = {
    "http": {"enabled", "url", "username", "password", "timeout_sec"},
    "mqtt": {
        "enabled",
        "host",
        "port",
        "username",
        "password",
        "topic_prefix",
        "topics",
        "retain",
    },
}
REPORTING_SCALAR_KEYS = {"interval_sec"}


def _validate_reporting_overrides(overrides: dict) -> Optional[str]:
    """
    Check a partial reporting config for unknown keys and wrong shapes.

    Args:
        overrides: Partial 'reporting' config from a request body

    Returns:
        An error message, or None when the overrides are acceptable
    """
    unknown = set(overrides) - set(REPORTING_SECTION_KEYS) - REPORTING_SCALAR_KEYS
    if unknown:
        return f"Unknown key(s): {', '.join(sorted(unknown))}"

    for section, allowed in REPORTING_SECTION_KEYS.items():
        if section not in overrides:
            continue

        value = overrides[section]
        if not isinstance(value, dict):
            # Without this a scalar replaces the whole section and then blows
            # up inside build_reporter as a 500 rather than a clean 400.
            return f"'{section}' must be an object"

        unknown = set(value) - allowed
        if unknown:
            return f"Unknown {section} key(s): {', '.join(sorted(unknown))}"

    return None


SECRET_KEYS = ("password",)
MASKED = "***"


def _mask_secrets(config: dict) -> dict:
    """
    Copy a config with secret values replaced.

    The reporting config carries the OpenEVSE and broker passwords, and this
    API has no auth of its own, so they are never echoed back.

    Args:
        config: Configuration dictionary

    Returns:
        A deep copy with secrets masked
    """
    masked = {}
    for key, value in config.items():
        if isinstance(value, dict):
            masked[key] = _mask_secrets(value)
        elif key in SECRET_KEYS and value:
            masked[key] = MASKED
        else:
            masked[key] = value
    return masked


class WebAPI:
    """Flask web API for the emulator."""

    def __init__(
        self,
        evse: "EVSEStateMachine",
        ev: "EVSimulator",
        host: str = "0.0.0.0",
        port: int = 8080,
        reporter=None,
        reporting_config: dict | None = None,
    ):
        """
        Initialize the web API.

        Args:
            evse: EVSE state machine instance
            ev: EV simulator instance
            host: Host to bind to
            port: Port to bind to
            reporter: Optional TelemetryReporter for the reporting endpoints
            reporting_config: The 'reporting' config the reporter was built
                from, used as the base for runtime reconfiguration
        """
        self.evse = evse
        self.ev = ev
        self.host = host
        self.port = port
        self.reporter = reporter
        self.reporting_config = reporting_config or {}

        # Create Flask app
        self.app = Flask(
            __name__,
            static_folder=os.path.join(os.path.dirname(__file__), "static"),
            static_url_path="",
        )
        CORS(self.app)

        # Create SocketIO instance
        self.socketio = SocketIO(
            self.app, cors_allowed_origins="*", async_mode="gevent"
        )

        # Register routes
        self._register_routes()

        # Set up state change callback
        self.evse.set_state_change_callback(self._on_state_change)

    def _register_routes(self):  # noqa: C901
        """Register all API routes."""

        # Serve index.html
        @self.app.route("/")
        def index():
            return send_from_directory(self.app.static_folder, "index.html")

        # Serve OpenAPI specification
        @self.app.route("/api/openapi.yaml", methods=["GET"])
        def get_openapi_spec():
            """Serve the OpenAPI specification file."""
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            return send_from_directory(root_dir, "openapi.yaml", mimetype="text/yaml")

        @self.app.route("/api/docs", methods=["GET"])
        def api_docs():
            """Serve API documentation page."""
            return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenEVSE Emulator API Documentation</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 900px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.6;
            color: #333;
        }
        h1 { color: #667eea; border-bottom: 3px solid #667eea; padding-bottom: 10px; }
        h2 { color: #764ba2; margin-top: 30px; }
        .info-box {
            background: #f0f4ff;
            border-left: 4px solid #667eea;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }
        code {
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }
        pre {
            background: #2d2d2d;
            color: #f8f8f2;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
        .download-btn {
            display: inline-block;
            background: #667eea;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            margin: 10px 0;
        }
        .download-btn:hover {
            background: #5568d3;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background: #667eea;
            color: white;
        }
        .back-link {
            margin-bottom: 20px;
        }
        .back-link a {
            color: #667eea;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="back-link">
        <a href="/">&larr; Back to Emulator UI</a>
    </div>

    <h1>OpenEVSE Emulator API Documentation</h1>

    <div class="info-box">
        <strong>Base URL:</strong> <code>http://localhost:8080</code><br>
        <strong>API Version:</strong> 1.0.0<br>
        <strong>OpenAPI Specification:</strong>
        <a href="/api/openapi.yaml" class="download-btn">
            Download openapi.yaml
        </a>
    </div>

    <h2>Quick Start</h2>
    <p>View the interactive API documentation using Swagger UI or any OpenAPI-compatible tool:</p>
    <pre>
# Using Docker with Swagger UI
docker run -p 8081:8080 -e SWAGGER_JSON=/api/openapi.yaml \\
  swaggerapi/swagger-ui

# Or use online Swagger Editor
# Visit: https://editor.swagger.io/
# Then File > Import URL > http://localhost:8080/api/openapi.yaml
    </pre>

    <h2>API Endpoints</h2>

    <h3>EVSE Control</h3>
    <table>
        <tr>
            <th>Method</th>
            <th>Endpoint</th>
            <th>Description</th>
        </tr>
        <tr>
            <td>GET</td>
            <td><code>/api/evse/status</code></td>
            <td>Get EVSE status</td>
        </tr>
        <tr>
            <td>GET</td>
            <td><code>/api/evse/version</code></td>
            <td>Get firmware version</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/evse/enable</code></td>
            <td>Enable charging</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/evse/disable</code></td>
            <td>Disable charging (sleep mode)</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/evse/reset</code></td>
            <td>Reset EVSE</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/evse/current</code></td>
            <td>Set current capacity (6-80A)</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/evse/service_level</code></td>
            <td>Set service level (L1/L2/Auto)</td>
        </tr>
    </table>

    <h3>EV Simulation</h3>
    <table>
        <tr>
            <th>Method</th>
            <th>Endpoint</th>
            <th>Description</th>
        </tr>
        <tr>
            <td>GET</td>
            <td><code>/api/ev/status</code></td>
            <td>Get EV status</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/ev/connect</code></td>
            <td>Connect EV</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/ev/disconnect</code></td>
            <td>Disconnect EV</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/ev/request_charge</code></td>
            <td>Request charge</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/ev/stop_charge</code></td>
            <td>Stop charging</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/ev/soc</code></td>
            <td>Set battery SoC (0-100%)</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/ev/max_rate</code></td>
            <td>Set max charge rate</td>
        </tr>
    </table>

    <h3>Error Simulation</h3>
    <table>
        <tr>
            <th>Method</th>
            <th>Endpoint</th>
            <th>Description</th>
        </tr>
        <tr>
            <td>GET</td>
            <td><code>/api/errors/status</code></td>
            <td>Get error status</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/errors/trigger</code></td>
            <td>Trigger error (gfci, stuck_relay, no_ground, etc.)</td>
        </tr>
        <tr>
            <td>POST</td>
            <td><code>/api/errors/clear</code></td>
            <td>Clear all errors</td>
        </tr>
    </table>

    <h3>Combined Status</h3>
    <table>
        <tr>
            <th>Method</th>
            <th>Endpoint</th>
            <th>Description</th>
        </tr>
        <tr>
            <td>GET</td>
            <td><code>/api/status</code></td>
            <td>Get combined EVSE and EV status</td>
        </tr>
    </table>

    <h2>Example Requests</h2>

    <h3>Connect EV and Start Charging</h3>
    <pre>
# Connect EV
curl -X POST http://localhost:8080/api/ev/connect

# Request charge
curl -X POST http://localhost:8080/api/ev/request_charge

# Set current to 16A
curl -X POST http://localhost:8080/api/evse/current \\
  -H "Content-Type: application/json" \\
  -d '{"amps": 16}'

# Get status
curl http://localhost:8080/api/status
    </pre>

    <h3>Trigger GFCI Error</h3>
    <pre>
curl -X POST http://localhost:8080/api/errors/trigger \\
  -H "Content-Type: application/json" \\
  -d '{"error": "gfci"}'
    </pre>

    <h2>WebSocket</h2>
    <p>Real-time updates are available via WebSocket at <code>ws://localhost:8080/ws</code></p>

    <h3>Message Types</h3>
    <ul>
        <li><code>state_change</code> - EVSE state changes</li>
        <li><code>status_update</code> - Periodic status updates</li>
        <li><code>error</code> - Error events</li>
    </ul>

    <h3>JavaScript Example</h3>
    <pre>
const ws = new WebSocket('ws://localhost:8080/ws');

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    console.log('Message type:', msg.type);
    console.log('Data:', msg.data);
};
    </pre>

    <h2>Full Specification</h2>
    <p>
        Download the complete OpenAPI 3.0 specification for use with code
        generators, testing tools, or API clients:
    </p>
    <a href="/api/openapi.yaml" class="download-btn">Download openapi.yaml</a>

    <footer style="margin-top: 50px; padding-top: 20px;
        border-top: 1px solid #ddd; color: #666;">
        <p>
            OpenEVSE Emulator API Documentation |
            <a href="https://github.com/jeremypoulter/OpenEVSE_Emulator">
                GitHub
            </a>
        </p>
    </footer>
</body>
</html>
            """

        # EVSE endpoints
        @self.app.route("/api/evse/status", methods=["GET"])
        def get_evse_status():
            return jsonify(self.evse.get_status())

        @self.app.route("/api/evse/version", methods=["GET"])
        def get_version():
            return jsonify(
                {
                    "firmware": self.evse.firmware_version,
                    "protocol": self.evse.protocol_version,
                }
            )

        @self.app.route("/api/evse/firmware", methods=["POST"])
        def set_firmware():
            """Select one of the supported firmware profiles."""
            try:
                from emulator.config import FIRMWARE_PROFILES
            except ImportError:
                from ..emulator.config import FIRMWARE_PROFILES

            data = request.get_json(silent=True) or {}
            version = data.get("version")
            profile = FIRMWARE_PROFILES.get(version)
            if profile is None:
                return jsonify({"error": "Unsupported firmware version"}), 400
            self.evse.set_firmware_profile(version)
            return jsonify(
                {
                    "success": True,
                    "firmware": version,
                    "protocol": self.evse.protocol_version,
                }
            )

        @self.app.route("/api/evse/enable", methods=["POST"])
        def enable_evse():
            if self.evse.enable():
                self._broadcast_status()
                return jsonify({"success": True})
            return (
                jsonify({"success": False, "error": "Cannot enable (errors present)"}),
                400,
            )

        @self.app.route("/api/evse/disable", methods=["POST"])
        def disable_evse():
            self.evse.disable()
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/evse/reset", methods=["POST"])
        def reset_evse():
            self.evse.reset()
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/evse/current", methods=["POST"])
        def set_current():
            data = request.get_json()
            if not data or "amps" not in data:
                return jsonify({"error": "Missing amps parameter"}), 400

            try:
                amps = int(data["amps"])
                if amps < 6 or amps > 80:
                    return (
                        jsonify({"error": "Current must be between 6 and 80 amps"}),
                        400,
                    )

                self.evse.current_capacity_amps = amps
                self._broadcast_status()
                return jsonify({"success": True})
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid amps value"}), 400

        @self.app.route("/api/evse/service_level", methods=["POST"])
        def set_service_level():
            data = request.get_json()
            if not data or "level" not in data:
                return jsonify({"error": "Missing level parameter"}), 400

            level = data["level"]
            if level not in ["L1", "L2", "Auto"]:
                return jsonify({"error": "Level must be L1, L2, or Auto"}), 400

            self.evse.service_level = level
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/evse/lcd", methods=["GET"])
        def get_lcd_display():
            """Get current LCD display content."""
            return jsonify(self.evse.lcd_display)

        @self.app.route("/api/evse/lcd", methods=["POST"])
        def set_lcd_display():
            """Set LCD display content."""
            data = request.get_json()
            row1 = data.get("row1")
            row2 = data.get("row2")
            self.evse.set_lcd_display(row1=row1, row2=row2)
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/evse/lcd/backlight", methods=["GET"])
        def get_lcd_backlight():
            """Get LCD backlight color."""
            lcd = self.evse.lcd_display
            return jsonify({"backlight_color": lcd.get("backlight_color", 7)})

        @self.app.route("/api/evse/lcd/backlight", methods=["POST"])
        def set_lcd_backlight():
            """Set LCD backlight color (0-7)."""
            data = request.get_json()
            color = data.get("color")
            if color is None or not (0 <= color <= 7):
                return jsonify({"error": "Color must be 0-7"}), 400
            self.evse.set_lcd_backlight_color(color)
            self._broadcast_status()
            return jsonify({"success": True})

        # EV endpoints
        @self.app.route("/api/ev/status", methods=["GET"])
        def get_ev_status():
            return jsonify(self.ev.get_status())

        @self.app.route("/api/ev/connect", methods=["POST"])
        def connect_ev():
            self.ev.connected = True
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/ev/disconnect", methods=["POST"])
        def disconnect_ev():
            self.ev.connected = False
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/ev/request_charge", methods=["POST"])
        def request_charge():
            self.ev.requesting_charge = True
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/ev/stop_charge", methods=["POST"])
        def stop_charge():
            self.ev.requesting_charge = False
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/ev/soc", methods=["POST"])
        def set_soc():
            data = request.get_json()
            if not data or "soc" not in data:
                return jsonify({"error": "Missing soc parameter"}), 400

            try:
                soc = float(data["soc"])
                if soc < 0 or soc > 100:
                    return jsonify({"error": "SoC must be between 0 and 100"}), 400

                self.ev.soc = soc
                self._broadcast_status()
                return jsonify({"success": True})
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid soc value"}), 400

        @self.app.route("/api/ev/max_rate", methods=["POST"])
        def set_max_rate():
            data = request.get_json()
            if not data or "amps" not in data:
                return jsonify({"error": "Missing amps parameter"}), 400

            try:
                amps = float(data["amps"])
                if amps < 0:
                    return jsonify({"error": "Max rate must be positive"}), 400

                # Convert amps to kW (assuming voltage from EVSE)
                voltage = self.evse.get_status()["voltage"] / 1000.0
                kw = (amps * voltage) / 1000.0
                self.ev.max_charge_rate_kw = kw
                self._broadcast_status()
                return jsonify({"success": True})
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid amps value"}), 400

        @self.app.route("/api/ev/charge_limit", methods=["POST"])
        def set_charge_limit():
            data = request.get_json()
            if not data or "charge_limit_soc" not in data:
                return jsonify({"error": "charge_limit_soc required"}), 400

            try:
                limit = float(data["charge_limit_soc"])
            except (TypeError, ValueError):
                return jsonify({"error": "charge_limit_soc must be a number"}), 400

            if not 0 <= limit <= 100:
                return jsonify({"error": "charge_limit_soc must be 0-100"}), 400

            self.ev.charge_limit_soc = limit
            self._broadcast_status()
            return jsonify({"success": True, "charge_limit_soc": limit})

        @self.app.route("/api/ev/range", methods=["POST"])
        def set_range():
            data = request.get_json()
            if not data or "range_km_at_full" not in data:
                return jsonify({"error": "range_km_at_full required"}), 400

            try:
                range_km = float(data["range_km_at_full"])
            except (TypeError, ValueError):
                return jsonify({"error": "range_km_at_full must be a number"}), 400

            if range_km <= 0:
                return jsonify({"error": "range_km_at_full must be > 0"}), 400

            self.ev.range_km_at_full = range_km
            self._broadcast_status()
            return jsonify({"success": True, "range_km_at_full": range_km})

        @self.app.route("/api/reporting/config", methods=["GET"])
        def get_reporting_config():
            return jsonify(_mask_secrets(self.reporting_config))

        @self.app.route("/api/reporting/config", methods=["POST"])
        def set_reporting_config():
            """
            Merge a partial reporting config and rebuild the reporter.

            The emulator is normally started before the OpenEVSE it reports to,
            so the HTTP target is rarely known at launch. This applies settings
            to the running emulator; it does not write config.json.
            """
            overrides = request.get_json(silent=True)
            if not isinstance(overrides, dict):
                return jsonify({"error": "A JSON object is required"}), 400

            error = _validate_reporting_overrides(overrides)
            if error:
                return jsonify({"error": error}), 400

            try:
                config = self._reconfigure_reporting(overrides)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

            return jsonify(
                {
                    "success": True,
                    "config": _mask_secrets(config),
                    "status": self.reporter.get_status(),
                }
            )

        @self.app.route("/api/reporting/status", methods=["GET"])
        def get_reporting_status():
            if self.reporter is None:
                return jsonify({"enabled": False, "running": False})
            return jsonify(self.reporter.get_status())

        @self.app.route("/api/reporting/publish", methods=["POST"])
        def publish_reporting():
            """Push telemetry immediately, rather than waiting for the interval."""
            if self.reporter is None or not self.reporter.enabled:
                return jsonify({"error": "Telemetry reporting is not configured"}), 409

            return jsonify(self.reporter.publish_once())

        @self.app.route("/api/ev/mode", methods=["POST"])
        def set_ev_mode():
            data = request.get_json()
            if not data or "direct_mode" not in data:
                return jsonify({"error": "Missing direct_mode parameter"}), 400

            self.ev.direct_mode = bool(data["direct_mode"])
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/ev/direct_current", methods=["POST"])
        def set_direct_current():
            data = request.get_json()
            if not data or "amps" not in data:
                return jsonify({"error": "Missing amps parameter"}), 400

            try:
                amps = float(data["amps"])
                if amps < 0:
                    return (
                        jsonify({"error": "Current must be non-negative"}),
                        400,
                    )

                self.ev.direct_current_amps = amps
                self._broadcast_status()
                return jsonify({"success": True})
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid amps value"}), 400

        @self.app.route("/api/ev/current_variance", methods=["POST"])
        def set_current_variance():
            data = request.get_json()
            if not data or "enabled" not in data:
                return jsonify({"error": "Missing enabled parameter"}), 400

            self.ev.current_variance_enabled = bool(data["enabled"])
            self._broadcast_status()
            return jsonify({"success": True})

        # Error simulation endpoints
        @self.app.route("/api/errors/trigger", methods=["POST"])
        def trigger_error():
            data = request.get_json()
            if not data or "error" not in data:
                return jsonify({"error": "Missing error parameter"}), 400

            error_map = {
                "gfci": ErrorFlags.GFCI_TRIP,
                "stuck_relay": ErrorFlags.STUCK_RELAY,
                "no_ground": ErrorFlags.NO_GROUND,
                "diode_check": ErrorFlags.DIODE_CHECK_FAILED,
                "over_temp": ErrorFlags.OVER_TEMPERATURE,
                "gfi_self_test": ErrorFlags.GFI_SELF_TEST_FAILED,
            }

            error_flag = error_map.get(data["error"])
            if error_flag is None:
                return jsonify({"error": "Unknown error type"}), 400

            self.evse.trigger_error(error_flag)
            self._broadcast_error(data["error"])
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/errors/clear", methods=["POST"])
        def clear_errors():
            self.evse.clear_errors()
            self._broadcast_status()
            return jsonify({"success": True})

        @self.app.route("/api/errors/status", methods=["GET"])
        def get_error_status():
            status = self.evse.get_status()
            return jsonify(
                {
                    "error_flags": status["error_flags"],
                    "error_counts": {
                        "gfci": status["gfci_count"],
                        "no_ground": status["no_ground_count"],
                        "stuck_relay": status["stuck_relay_count"],
                    },
                }
            )

        # Combined status endpoint
        @self.app.route("/api/status", methods=["GET"])
        def get_combined_status():
            return jsonify({"evse": self.evse.get_status(), "ev": self.ev.get_status()})

    def _on_state_change(self, new_state):
        """Called when EVSE state changes."""
        self.socketio.emit(
            "state_change", {"state": int(new_state), "state_name": new_state.name}
        )

    def _reconfigure_reporting(self, overrides: dict) -> dict:
        """
        Apply a partial reporting config, replacing the running reporter.

        Args:
            overrides: Partial 'reporting' config to merge over the current one

        Returns:
            The merged configuration now in effect

        Raises:
            ValueError: If the merged configuration is invalid, in which case
                the existing reporter is left untouched and still running
        """
        merged = merge_config(self.reporting_config, overrides)

        # Built before anything is torn down: an invalid config must raise
        # here, leaving the current reporter running rather than stopping it
        # and then failing to replace it.
        replacement = build_reporter(self.ev, merged)

        if self.reporter is not None:
            self.reporter.stop()

        self.reporter = replacement
        self.reporting_config = merged

        # A no-op when no transport is configured, so this also covers
        # disabling reporting entirely.
        replacement.start()

        return merged

    def _broadcast_status(self):
        """Broadcast status update via WebSocket."""
        evse_status = self.evse.get_status()
        ev_status = self.ev.get_status()

        self.socketio.emit("status_update", {"evse": evse_status, "ev": ev_status})

    def _broadcast_error(self, error_type: str):
        """Broadcast error event via WebSocket."""
        self.socketio.emit(
            "error", {"error": error_type, "message": f"{error_type} error triggered"}
        )

    def run(self):
        """Run the web server."""
        print(f"Starting web server on http://{self.host}:{self.port}")
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False)

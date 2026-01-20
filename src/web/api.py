"""
Flask web API for controlling the emulator.

Provides REST endpoints and WebSocket interface.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
import os
from typing import TYPE_CHECKING

# Handle imports for both direct execution and test execution
try:
    from emulator.evse import ErrorFlags
except ImportError:
    # When imported as src.web.api from tests
    from ..emulator.evse import ErrorFlags

if TYPE_CHECKING:
    try:
        from emulator.evse import EVSEStateMachine
        from emulator.ev import EVSimulator
    except ImportError:
        from ..emulator.evse import EVSEStateMachine
        from ..emulator.ev import EVSimulator


class WebAPI:
    """Flask web API for the emulator."""

    def __init__(
        self,
        evse: "EVSEStateMachine",
        ev: "EVSimulator",
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        """
        Initialize the web API.

        Args:
            evse: EVSE state machine instance
            ev: EV simulator instance
            host: Host to bind to
            port: Port to bind to
        """
        self.evse = evse
        self.ev = ev
        self.host = host
        self.port = port

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

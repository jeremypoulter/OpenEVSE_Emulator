"""
Unit tests for the Web API.

Tests all REST endpoints and WebSocket functionality.
"""

import pytest
import json
from src.emulator.evse import EVSEStateMachine, ErrorFlags
from src.emulator.ev import EVSimulator
from src.web.api import WebAPI


@pytest.fixture
def evse():
    """Create an EVSE instance for testing."""
    return EVSEStateMachine()


@pytest.fixture
def ev():
    """Create an EV instance for testing."""
    return EVSimulator()


@pytest.fixture
def api_client(evse, ev):
    """Create a Flask test client."""
    api = WebAPI(evse, ev, host="127.0.0.1", port=8080)
    api.app.config["TESTING"] = True
    with api.app.test_client() as client:
        yield client


class TestStatusEndpoints:
    """Test status-related API endpoints."""

    def test_get_status(self, api_client):
        """Test GET /api/status endpoint."""
        response = api_client.get("/api/status")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "evse" in data
        assert "ev" in data
        assert "state" in data["evse"]
        assert "current_capacity" in data["evse"]
        assert "connected" in data["ev"]
        assert "soc" in data["ev"]

    def test_get_evse_status(self, api_client):
        """Test GET /api/evse/status endpoint."""
        response = api_client.get("/api/evse/status")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "state" in data
        assert "state_name" in data
        assert "current_capacity" in data
        assert "service_level" in data
        assert "temperature_ds" in data
        assert "error_flags" in data

    def test_set_firmware_profile(self, api_client):
        """Test selecting the firmware profile from the UI API."""
        response = api_client.post(
            "/api/evse/firmware",
            data=json.dumps({"version": "9.0.0"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert json.loads(response.data)["firmware"] == "9.0.0"

        response = api_client.post(
            "/api/evse/firmware",
            data=json.dumps({"version": "unsupported"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_get_ev_status(self, api_client):
        """Test GET /api/ev/status endpoint."""
        response = api_client.get("/api/ev/status")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "connected" in data
        assert "soc" in data
        assert "battery_capacity_kwh" in data
        assert "max_charge_rate_kw" in data


class TestEVSEControlEndpoints:
    """Test EVSE control API endpoints."""

    def test_enable_evse(self, api_client):
        """Test POST /api/evse/enable endpoint."""
        response = api_client.post("/api/evse/enable")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_disable_evse(self, api_client):
        """Test POST /api/evse/disable endpoint."""
        response = api_client.post("/api/evse/disable")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_set_current_capacity_valid(self, api_client):
        """Test POST /api/evse/current with valid value."""
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": 16}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was set
        status = api_client.get("/api/evse/status")
        status_data = json.loads(status.data)
        assert status_data["current_capacity"] == 16

    def test_set_current_capacity_invalid(self, api_client):
        """Test POST /api/evse/current with invalid value."""
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": 100}),
            content_type="application/json",
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data

    def test_set_current_capacity_missing_param(self, api_client):
        """Test POST /api/evse/current without amps parameter."""
        response = api_client.post(
            "/api/evse/current", data=json.dumps({}), content_type="application/json"
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data

    def test_set_service_level(self, api_client):
        """Test POST /api/evse/service_level endpoint."""
        response = api_client.post(
            "/api/evse/service_level",
            data=json.dumps({"level": "L2"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_reset_evse(self, api_client):
        """Test POST /api/evse/reset endpoint."""
        response = api_client.post("/api/evse/reset")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True


class TestEVControlEndpoints:
    """Test EV control API endpoints."""

    def test_connect_ev(self, api_client):
        """Test POST /api/ev/connect endpoint."""
        response = api_client.post("/api/ev/connect")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was connected
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["connected"] is True

    def test_disconnect_ev(self, api_client):
        """Test POST /api/ev/disconnect endpoint."""
        # First connect
        api_client.post("/api/ev/connect")

        # Then disconnect
        response = api_client.post("/api/ev/disconnect")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was disconnected
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["connected"] is False

    def test_set_ev_soc_valid(self, api_client):
        """Test POST /api/ev/soc with valid value."""
        response = api_client.post(
            "/api/ev/soc", data=json.dumps({"soc": 50}), content_type="application/json"
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was set
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["soc"] == 50

    def test_set_ev_soc_invalid(self, api_client):
        """Test POST /api/ev/soc with invalid value."""
        response = api_client.post(
            "/api/ev/soc",
            data=json.dumps({"soc": 150}),
            content_type="application/json",
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data

    def test_set_ev_max_rate(self, api_client):
        """Test POST /api/ev/max_rate endpoint."""
        response = api_client.post(
            "/api/ev/max_rate",
            data=json.dumps({"amps": 16}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True


class TestErrorSimulationEndpoints:
    """Test error simulation API endpoints."""

    def test_trigger_gfci_error(self, api_client):
        """Test POST /api/errors/trigger endpoint with GFCI."""
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "gfci"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

        # Verify error was set
        status = api_client.get("/api/evse/status")
        status_data = json.loads(status.data)
        assert status_data["error_flags"] & ErrorFlags.GFCI_TRIP

    def test_trigger_stuck_relay_error(self, api_client):
        """Test POST /api/errors/trigger endpoint with stuck relay."""
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "stuck_relay"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_trigger_no_ground_error(self, api_client):
        """Test POST /api/errors/trigger endpoint with no ground."""
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "no_ground"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_trigger_diode_check_error(self, api_client):
        """Test POST /api/errors/trigger endpoint with diode check."""
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "diode_check"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_trigger_over_temperature_error(self, api_client):
        """Test POST /api/errors/trigger endpoint with over temp."""
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "over_temp"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_trigger_gfci_self_test_error(self, api_client):
        """Test POST /api/errors/trigger endpoint with GFI self test."""
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "gfi_self_test"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

    def test_clear_errors(self, api_client):
        """Test POST /api/errors/clear endpoint."""
        # First trigger an error
        api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "gfci"}),
            content_type="application/json",
        )

        # Then clear it
        response = api_client.post("/api/errors/clear")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

        # Verify errors were cleared
        status = api_client.get("/api/evse/status")
        status_data = json.loads(status.data)
        assert status_data["error_flags"] == 0


class TestStaticFilesEndpoints:
    """Test static file serving."""

    def test_serve_index(self, api_client):
        """Test GET / serves index.html."""
        response = api_client.get("/")
        assert response.status_code in [200, 404]  # 404 if static files not in test env

    def test_serve_openapi_spec(self, api_client):
        """Test GET /api/openapi.yaml endpoint."""
        response = api_client.get("/api/openapi.yaml")
        # May return 200 with file or 404 if file not found in test environment
        assert response.status_code in [200, 404]

    def test_serve_api_docs(self, api_client):
        """Test GET /api/docs endpoint."""
        response = api_client.get("/api/docs")
        assert response.status_code == 200
        assert b"API Documentation" in response.data


class TestErrorHandling:
    """Test error handling in API."""

    def test_invalid_json_request(self, api_client):
        """Test handling of invalid JSON in request body."""
        response = api_client.post(
            "/api/evse/current", data="invalid json", content_type="application/json"
        )
        assert response.status_code in [400, 500]

    def test_method_not_allowed(self, api_client):
        """Test wrong HTTP method returns 405."""
        # Try DELETE on a GET/POST endpoint - this should return 405
        response = api_client.delete("/api/status")
        assert response.status_code == 405

    def test_not_found(self, api_client):
        """Test nonexistent endpoint returns 404."""
        response = api_client.get("/api/nonexistent")
        assert response.status_code == 404


class TestIntegrationScenarios:
    """Test complete API usage scenarios."""

    def test_full_charging_workflow(self, api_client):
        """Test complete workflow: enable, connect, charge, disconnect."""
        # 1. Enable EVSE
        response = api_client.post("/api/evse/enable")
        assert response.status_code == 200

        # 2. Connect EV
        response = api_client.post("/api/ev/connect")
        assert response.status_code == 200

        # 3. Set charging current
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": 16}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # 4. Check status
        response = api_client.get("/api/status")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["ev"]["connected"] is True

        # 5. Disconnect EV
        response = api_client.post("/api/ev/disconnect")
        assert response.status_code == 200

    def test_error_recovery_workflow(self, api_client):
        """Test error triggering and recovery."""
        # 1. Enable EVSE
        api_client.post("/api/evse/enable")

        # 2. Trigger error
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "gfci"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # 3. Verify EVSE is in error state
        status = api_client.get("/api/evse/status")
        data = json.loads(status.data)
        assert data["error_flags"] != 0

        # 4. Clear errors
        response = api_client.post("/api/errors/clear")
        assert response.status_code == 200

        # 5. Verify errors cleared
        status = api_client.get("/api/evse/status")
        data = json.loads(status.data)
        assert data["error_flags"] == 0


class TestLCDEndpoints:
    """Test LCD display endpoints."""

    def test_get_lcd_display(self, api_client):
        """Test getting LCD display content."""
        response = api_client.get("/api/evse/lcd")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "row1" in data
        assert "row2" in data
        assert "backlight_color" in data
        # LCD returns actual content which may be less than 16 chars
        assert len(data["row1"]) <= 16
        assert len(data["row2"]) <= 16

    def test_set_lcd_display(self, api_client):
        """Test setting LCD display content."""
        response = api_client.post(
            "/api/evse/lcd",
            data=json.dumps({"row1": "OpenEVSE", "row2": "Ready"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Verify content was set
        lcd_response = api_client.get("/api/evse/lcd")
        data = json.loads(lcd_response.data)
        assert "OpenEVSE" in data["row1"]
        assert "Ready" in data["row2"]

    def test_set_lcd_display_partial(self, api_client):
        """Test setting only one row of LCD display."""
        # Set only row1
        response = api_client.post(
            "/api/evse/lcd",
            data=json.dumps({"row1": "Line 1"}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Set only row2
        response = api_client.post(
            "/api/evse/lcd",
            data=json.dumps({"row2": "Line 2"}),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_get_lcd_backlight(self, api_client):
        """Test getting LCD backlight color."""
        response = api_client.get("/api/evse/lcd/backlight")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "backlight_color" in data
        assert 0 <= data["backlight_color"] <= 7

    def test_set_lcd_backlight(self, api_client):
        """Test setting LCD backlight color."""
        response = api_client.post(
            "/api/evse/lcd/backlight",
            data=json.dumps({"color": 3}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Verify color was set
        lcd_response = api_client.get("/api/evse/lcd/backlight")
        data = json.loads(lcd_response.data)
        assert data["backlight_color"] == 3

    def test_set_lcd_backlight_invalid_color(self, api_client):
        """Test setting invalid backlight color."""
        # Too high
        response = api_client.post(
            "/api/evse/lcd/backlight",
            data=json.dumps({"color": 10}),
            content_type="application/json",
        )
        assert response.status_code == 400

        # Negative
        response = api_client.post(
            "/api/evse/lcd/backlight",
            data=json.dumps({"color": -1}),
            content_type="application/json",
        )
        assert response.status_code == 400

        # Missing parameter
        response = api_client.post(
            "/api/evse/lcd/backlight",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestEnableErrorHandling:
    """Test enable endpoint error handling."""

    def test_enable_with_errors_fails(self, api_client):
        """Test that enabling fails when errors are present."""
        # Trigger an error first
        api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "gfci"}),
            content_type="application/json",
        )

        # Try to enable (should fail)
        response = api_client.post("/api/evse/enable")
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data
        assert data["success"] is False


class TestDirectModeEndpoints:
    """Test direct current control API endpoints."""

    def test_set_direct_mode(self, api_client):
        """Test POST /api/ev/mode endpoint."""
        response = api_client.post(
            "/api/ev/mode",
            data=json.dumps({"direct_mode": True}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was set
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["direct_mode"] is True

    def test_set_direct_mode_off(self, api_client):
        """Test switching back to battery mode."""
        # Enable direct mode
        api_client.post(
            "/api/ev/mode",
            data=json.dumps({"direct_mode": True}),
            content_type="application/json",
        )

        # Disable direct mode
        response = api_client.post(
            "/api/ev/mode",
            data=json.dumps({"direct_mode": False}),
            content_type="application/json",
        )
        assert response.status_code == 200

        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["direct_mode"] is False

    def test_set_direct_mode_missing_param(self, api_client):
        """Test POST /api/ev/mode without required parameter."""
        response = api_client.post(
            "/api/ev/mode",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_set_direct_current(self, api_client):
        """Test POST /api/ev/direct_current endpoint."""
        response = api_client.post(
            "/api/ev/direct_current",
            data=json.dumps({"amps": 20.0}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was set
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["direct_current_amps"] == 20.0

    def test_set_direct_current_negative(self, api_client):
        """Test POST /api/ev/direct_current with negative value."""
        response = api_client.post(
            "/api/ev/direct_current",
            data=json.dumps({"amps": -5.0}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_set_direct_current_missing_param(self, api_client):
        """Test POST /api/ev/direct_current without required parameter."""
        response = api_client.post(
            "/api/ev/direct_current",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_set_current_variance(self, api_client):
        """Test POST /api/ev/current_variance endpoint."""
        response = api_client.post(
            "/api/ev/current_variance",
            data=json.dumps({"enabled": True}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was set
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["current_variance_enabled"] is True

    def test_set_current_variance_off(self, api_client):
        """Test disabling current variance."""
        # Enable first
        api_client.post(
            "/api/ev/current_variance",
            data=json.dumps({"enabled": True}),
            content_type="application/json",
        )

        # Disable
        response = api_client.post(
            "/api/ev/current_variance",
            data=json.dumps({"enabled": False}),
            content_type="application/json",
        )
        assert response.status_code == 200

        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["current_variance_enabled"] is False

    def test_set_current_variance_missing_param(self, api_client):
        """Test POST /api/ev/current_variance without required parameter."""
        response = api_client.post(
            "/api/ev/current_variance",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_status_includes_new_fields(self, api_client):
        """Test that /api/status includes direct mode fields."""
        response = api_client.get("/api/status")
        assert response.status_code == 200

        data = json.loads(response.data)
        ev = data["ev"]
        assert "direct_mode" in ev
        assert "direct_current_amps" in ev
        assert "current_variance_enabled" in ev


class TestVehicleTelemetryEndpoints:
    """EV range/charge-limit setters and the reporting endpoints."""

    def test_set_charge_limit(self, api_client, ev):
        response = api_client.post(
            "/api/ev/charge_limit", json={"charge_limit_soc": 80}
        )
        assert response.status_code == 200
        assert ev.charge_limit_soc == 80.0

    def test_set_charge_limit_rejects_out_of_range(self, api_client):
        response = api_client.post(
            "/api/ev/charge_limit", json={"charge_limit_soc": 120}
        )
        assert response.status_code == 400

    def test_set_charge_limit_rejects_non_numeric(self, api_client):
        response = api_client.post(
            "/api/ev/charge_limit", json={"charge_limit_soc": "full"}
        )
        assert response.status_code == 400

    def test_set_charge_limit_requires_field(self, api_client):
        assert api_client.post("/api/ev/charge_limit", json={}).status_code == 400

    def test_set_charge_limit_rejects_bool(self, api_client, ev):
        """
        bool is a subclass of int, so float(True) == 1.0 would otherwise set
        a 1% charge limit from a JSON boolean.
        """
        response = api_client.post(
            "/api/ev/charge_limit", json={"charge_limit_soc": True}
        )
        assert response.status_code == 400
        assert ev.charge_limit_soc != 1.0

    def test_set_range(self, api_client, ev):
        response = api_client.post("/api/ev/range", json={"range_km_at_full": 500})
        assert response.status_code == 200
        assert ev.range_km_at_full == 500.0

    def test_set_range_rejects_non_positive(self, api_client):
        response = api_client.post("/api/ev/range", json={"range_km_at_full": 0})
        assert response.status_code == 400

    def test_set_range_rejects_bool(self, api_client, ev):
        response = api_client.post("/api/ev/range", json={"range_km_at_full": True})
        assert response.status_code == 400
        assert ev.range_km_at_full != 1.0

    def test_reporting_status_without_a_reporter(self, api_client):
        """The endpoint must answer even when reporting is not wired up."""
        response = api_client.get("/api/reporting/status")
        assert response.status_code == 200
        assert json.loads(response.data)["enabled"] is False

    def test_status_shape_matches_a_configured_reporters_disabled_state(self, evse, ev):
        """
        With no reporter wired up, the response must carry the same keys as a
        real reporter with nothing enabled - not a thinner, hand-rolled shape
        a client would need to special-case.
        """
        from src.emulator.telemetry import TelemetryReporter

        without = WebAPI(evse, ev)
        without.app.config["TESTING"] = True
        with_disabled = WebAPI(evse, ev, reporter=TelemetryReporter(ev))
        with_disabled.app.config["TESTING"] = True

        with without.app.test_client() as a, with_disabled.app.test_client() as b:
            data_a = json.loads(a.get("/api/reporting/status").data)
            data_b = json.loads(b.get("/api/reporting/status").data)

        assert set(data_a) == set(data_b)

    def test_publish_without_a_reporter_is_a_conflict(self, api_client):
        assert api_client.post("/api/reporting/publish").status_code == 409

    def test_reporting_status_with_a_reporter(self, evse, ev):
        from src.emulator.telemetry import HttpTelemetryReporter, TelemetryReporter

        reporter = TelemetryReporter(ev, http=HttpTelemetryReporter(url="http://evse"))
        api = WebAPI(evse, ev, host="127.0.0.1", port=8080, reporter=reporter)
        api.app.config["TESTING"] = True

        with api.app.test_client() as client:
            data = json.loads(client.get("/api/reporting/status").data)

        assert data["enabled"] is True
        assert data["http"]["url"] == "http://evse/status"

    def test_publish_returns_per_transport_results(self, evse, ev):
        from unittest.mock import MagicMock

        from src.emulator.telemetry import TelemetryReporter

        http = MagicMock()
        http.send.return_value = True
        reporter = TelemetryReporter(ev, http=http)
        api = WebAPI(evse, ev, host="127.0.0.1", port=8080, reporter=reporter)
        api.app.config["TESTING"] = True

        with api.app.test_client() as client:
            data = json.loads(client.post("/api/reporting/publish").data)

        assert data["results"] == {"http": True}
        assert data["telemetry"]["battery_level"] == ev.soc


class TestReportingConfigEndpoint:
    """Runtime reconfiguration of telemetry reporting.

    The emulator is normally started before the OpenEVSE it reports to, so the
    HTTP target has to be settable after launch.
    """

    def _api(self, evse, ev, config=None):
        from src.emulator.telemetry import build_reporter

        config = config or {}
        api = WebAPI(
            evse,
            ev,
            host="127.0.0.1",
            port=8080,
            reporter=build_reporter(ev, config),
            reporting_config=config,
        )
        api.app.config["TESTING"] = True
        return api

    def test_get_returns_current_config(self, evse, ev):
        api = self._api(evse, ev, {"interval_sec": 30})
        with api.app.test_client() as client:
            data = json.loads(client.get("/api/reporting/config").data)
        assert data["interval_sec"] == 30

    def test_http_target_can_be_set_after_startup(self, evse, ev):
        api = self._api(evse, ev)

        with api.app.test_client() as client:
            response = client.post(
                "/api/reporting/config",
                json={"http": {"enabled": True, "url": "http://openevse.local"}},
            )

        assert response.status_code == 200
        assert api.reporter.enabled is True
        assert api.reporter.http.url == "http://openevse.local/status"
        api.reporter.stop()

    def test_partial_update_keeps_other_settings(self, evse, ev):
        api = self._api(
            evse,
            ev,
            {
                "interval_sec": 30,
                "http": {"enabled": True, "url": "http://evse", "username": "admin"},
            },
        )

        with api.app.test_client() as client:
            client.post("/api/reporting/config", json={"interval_sec": 5})

        assert api.reporting_config["interval_sec"] == 5
        assert api.reporting_config["http"]["username"] == "admin"
        assert api.reporter.http.url == "http://evse/status"
        api.reporter.stop()

    def test_reporting_can_be_disabled_again(self, evse, ev):
        api = self._api(evse, ev, {"http": {"enabled": True, "url": "http://evse"}})

        with api.app.test_client() as client:
            client.post("/api/reporting/config", json={"http": {"enabled": False}})

        assert api.reporter.enabled is False
        assert api.reporter.running is False

    def test_invalid_config_leaves_the_reporter_running(self, evse, ev):
        """A bad update must not tear down working reporting."""
        api = self._api(evse, ev, {"http": {"enabled": True, "url": "http://evse"}})
        api.reporter.start()
        original = api.reporter

        with api.app.test_client() as client:
            response = client.post(
                "/api/reporting/config", json={"mqtt": {"enabled": True}}
            )

        assert response.status_code == 400
        assert api.reporter is original
        assert api.reporter.running is True
        api.reporter.stop()

    def test_unknown_key_is_rejected(self, evse, ev):
        """A typo would otherwise be merged in and silently do nothing."""
        api = self._api(evse, ev)

        with api.app.test_client() as client:
            response = client.post("/api/reporting/config", json={"htp": {}})

        assert response.status_code == 400
        assert "htp" in json.loads(response.data)["error"]

    def test_unknown_nested_key_is_rejected(self, evse, ev):
        """A typo inside a section is the same silent no-op, one level down."""
        api = self._api(evse, ev, {"http": {"enabled": False, "url": None}})

        with api.app.test_client() as client:
            response = client.post(
                "/api/reporting/config", json={"http": {"enabeld": True}}
            )

        assert response.status_code == 400
        assert "enabeld" in json.loads(response.data)["error"]
        # The bad key must not have been merged into the stored config.
        assert "enabeld" not in api.reporting_config["http"]

    def test_unknown_nested_mqtt_key_is_rejected(self, evse, ev):
        api = self._api(evse, ev)

        with api.app.test_client() as client:
            response = client.post(
                "/api/reporting/config", json={"mqtt": {"hostname": "broker"}}
            )

        assert response.status_code == 400
        assert "hostname" in json.loads(response.data)["error"]

    def test_non_object_section_is_a_bad_request_not_a_crash(self, evse, ev):
        """A scalar section would otherwise replace the dict and 500."""
        api = self._api(evse, ev, {"http": {"enabled": False, "url": None}})

        with api.app.test_client() as client:
            response = client.post("/api/reporting/config", json={"http": "yes"})

        assert response.status_code == 400
        assert isinstance(api.reporting_config["http"], dict)

    def test_every_config_key_is_accepted(self, evse, ev):
        """The allow-list must not reject a key the config file supports."""
        from src.emulator.config import default_config

        api = self._api(evse, ev)
        reporting = default_config()["reporting"]

        with api.app.test_client() as client:
            response = client.post("/api/reporting/config", json=reporting)

        assert response.status_code == 200

    def test_empty_password_is_masked_not_echoed(self, evse, ev):
        """
        Masking was gated on truthiness, so an empty password came back as "",
        which contradicts the documented guarantee and reveals it is blank.
        """
        api = self._api(evse, ev, {"http": {"enabled": False, "password": ""}})

        with api.app.test_client() as client:
            data = json.loads(client.get("/api/reporting/config").data)

        assert data["http"]["password"] == "***"

    def test_null_password_stays_null(self, evse, ev):
        """Masking must not invent a secret where none is set."""
        api = self._api(evse, ev, {"http": {"enabled": False, "password": None}})

        with api.app.test_client() as client:
            data = json.loads(client.get("/api/reporting/config").data)

        assert data["http"]["password"] is None

    def test_non_object_body_is_rejected(self, evse, ev):
        api = self._api(evse, ev)
        with api.app.test_client() as client:
            assert client.post("/api/reporting/config", json=[]).status_code == 400

    def test_posting_back_a_masked_password_leaves_it_unchanged(self, evse, ev):
        """
        The natural read-modify-write pattern - GET the config, change one
        field, POST the rest back - must not overwrite the real password
        with the literal string "***" it was masked as.
        """
        api = self._api(
            evse,
            ev,
            {"http": {"enabled": True, "url": "http://evse", "password": "secret"}},
        )

        with api.app.test_client() as client:
            fetched = json.loads(client.get("/api/reporting/config").data)
            assert fetched["http"]["password"] == "***"

            fetched["interval_sec"] = 45
            response = client.post("/api/reporting/config", json=fetched)

        assert response.status_code == 200
        assert api.reporting_config["http"]["password"] == "secret"
        assert api.reporting_config["interval_sec"] == 45
        api.reporter.stop()

    def test_an_explicit_password_change_still_applies(self, evse, ev):
        """Stripping the mask must not block a genuine password update."""
        api = self._api(
            evse,
            ev,
            {"http": {"enabled": True, "url": "http://evse", "password": "old"}},
        )

        with api.app.test_client() as client:
            client.post("/api/reporting/config", json={"http": {"password": "new"}})

        assert api.reporting_config["http"]["password"] == "new"
        api.reporter.stop()

    def test_passwords_are_never_echoed_back(self, evse, ev):
        api = self._api(evse, ev)

        with api.app.test_client() as client:
            posted = client.post(
                "/api/reporting/config",
                json={
                    "http": {
                        "enabled": True,
                        "url": "http://evse",
                        "password": "hunter2",
                    }
                },
            )
            fetched = client.get("/api/reporting/config")

        assert "hunter2" not in posted.get_data(as_text=True)
        assert "hunter2" not in fetched.get_data(as_text=True)
        assert json.loads(fetched.data)["http"]["password"] == "***"
        # The real password is still in use, just not echoed.
        assert api.reporter.http.auth == ("", "hunter2")
        api.reporter.stop()

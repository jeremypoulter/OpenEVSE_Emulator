"""
Tests based on the OpenAPI specification.

Validates that the API implementation matches the OpenAPI spec.
"""

import pytest
import json
import yaml
from pathlib import Path
from src.emulator.evse import EVSEStateMachine
from src.emulator.ev import EVSimulator
from src.web.api import WebAPI


@pytest.fixture
def openapi_spec():
    """Load the OpenAPI specification."""
    spec_path = Path(__file__).parent.parent / "openapi.yaml"
    if not spec_path.exists():
        pytest.skip("OpenAPI spec not found")

    with open(spec_path, "r") as f:
        return yaml.safe_load(f)


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


class TestOpenAPICompliance:
    """Test that API matches OpenAPI specification."""

    def test_all_get_endpoints_exist(self, api_client, openapi_spec):
        """Test that all GET endpoints from spec are implemented."""
        paths = openapi_spec.get("paths", {})

        for path, methods in paths.items():
            if "get" in methods:
                # Replace path parameters with test values
                test_path = path

                response = api_client.get(test_path)
                # Should not return 404 (endpoint exists)
                assert response.status_code != 404, f"GET endpoint {path} not found"

    def test_all_post_endpoints_exist(self, api_client, openapi_spec):
        """Test that all POST endpoints from spec are implemented."""
        paths = openapi_spec.get("paths", {})

        for path, methods in paths.items():
            if "post" in methods:
                test_path = path

                # Send minimal valid request
                response = api_client.post(
                    test_path, data=json.dumps({}), content_type="application/json"
                )
                # Should not return 404 (endpoint exists)
                assert response.status_code != 404, f"POST endpoint {path} not found"

    def test_status_endpoint_response_schema(self, api_client, openapi_spec):
        """Test /api/status response matches schema."""
        response = api_client.get("/api/status")
        assert response.status_code == 200

        data = json.loads(response.data)

        # Validate required fields based on spec
        assert "evse" in data
        assert "ev" in data

        # EVSE should have required fields
        evse_data = data["evse"]
        assert "state" in evse_data
        assert "current_capacity" in evse_data

        # EV should have required fields
        ev_data = data["ev"]
        assert "connected" in ev_data
        assert "soc" in ev_data

    def test_evse_status_response_schema(self, api_client, openapi_spec):
        """Test /api/evse/status response matches schema."""
        response = api_client.get("/api/evse/status")
        assert response.status_code == 200

        data = json.loads(response.data)

        # Validate required fields
        required_fields = [
            "state",
            "state_name",
            "current_capacity",
            "service_level",
            "temperature_ds",
            "error_flags",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        # Validate data types
        assert isinstance(data["state"], int)
        assert isinstance(data["current_capacity"], (int, float))
        assert isinstance(data["service_level"], str)
        assert isinstance(data["temperature_ds"], (int, float))
        assert isinstance(data["error_flags"], int)

    def test_ev_status_response_schema(self, api_client, openapi_spec):
        """Test /api/ev/status response matches schema."""
        response = api_client.get("/api/ev/status")
        assert response.status_code == 200

        data = json.loads(response.data)

        # Validate required fields (using actual field names)
        required_fields = [
            "connected",
            "soc",
            "battery_capacity_kwh",
            "max_charge_rate_kw",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        # Validate data types
        assert isinstance(data["connected"], bool)
        assert isinstance(data["soc"], (int, float))
        assert isinstance(data["battery_capacity_kwh"], (int, float))
        assert isinstance(data["max_charge_rate_kw"], (int, float))


class TestOpenAPIRequestValidation:
    """Test request validation according to OpenAPI spec."""

    def test_set_current_validates_range(self, api_client):
        """Test that current capacity validates min/max from spec."""
        # Valid value (within spec range 6-80)
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": 16}),
            content_type="application/json",
        )
        assert response.status_code == 200

        # Below minimum
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": 5}),
            content_type="application/json",
        )
        assert response.status_code == 400

        # Above maximum
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": 81}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_set_soc_validates_range(self, api_client):
        """Test that SoC validates 0-100 range from spec."""
        # Valid value
        response = api_client.post(
            "/api/ev/soc", data=json.dumps({"soc": 50}), content_type="application/json"
        )
        assert response.status_code == 200

        # Below minimum
        response = api_client.post(
            "/api/ev/soc", data=json.dumps({"soc": -1}), content_type="application/json"
        )
        assert response.status_code == 400

        # Above maximum
        response = api_client.post(
            "/api/ev/soc",
            data=json.dumps({"soc": 101}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_set_service_level_validates_enum(self, api_client):
        """Test that service level validates enum values from spec."""
        # Valid values ('L1', 'L2', 'Auto')
        for level in ["L1", "L2", "Auto"]:
            response = api_client.post(
                "/api/evse/service_level",
                data=json.dumps({"level": level}),
                content_type="application/json",
            )
            assert response.status_code == 200

        # Invalid value
        response = api_client.post(
            "/api/evse/service_level",
            data=json.dumps({"level": "L3"}),
            content_type="application/json",
        )
        assert response.status_code == 400


class TestOpenAPIResponseCodes:
    """Test that response codes match OpenAPI spec."""

    def test_successful_requests_return_200(self, api_client):
        """Test that successful operations return 200."""
        endpoints = [
            ("GET", "/api/status"),
            ("GET", "/api/evse/status"),
            ("GET", "/api/ev/status"),
            ("POST", "/api/evse/enable"),
            ("POST", "/api/evse/disable"),
            ("POST", "/api/ev/connect"),
            ("POST", "/api/ev/disconnect"),
        ]

        for method, path in endpoints:
            if method == "GET":
                response = api_client.get(path)
            else:
                response = api_client.post(path)

            assert response.status_code == 200, f"{method} {path} did not return 200"

    def test_invalid_requests_return_400(self, api_client):
        """Test that invalid requests return 400."""
        # Missing required parameter
        response = api_client.post(
            "/api/evse/current", data=json.dumps({}), content_type="application/json"
        )
        assert response.status_code == 400

        # Invalid parameter value
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": "invalid"}),
            content_type="application/json",
        )
        assert response.status_code in [400, 500]

    def test_not_found_returns_404(self, api_client):
        """Test that nonexistent endpoints return 404."""
        response = api_client.get("/api/does-not-exist")
        assert response.status_code == 404

    def test_method_not_allowed_returns_405(self, api_client):
        """Test that wrong HTTP methods return 405."""
        # Try DELETE on a GET-only endpoint
        response = api_client.delete("/api/status")
        assert response.status_code == 405


class TestOpenAPIContentTypes:
    """Test content types according to OpenAPI spec."""

    def test_json_responses_have_correct_content_type(self, api_client):
        """Test that JSON endpoints return application/json."""
        response = api_client.get("/api/status")
        assert response.status_code == 200
        assert "application/json" in response.content_type

    def test_yaml_endpoint_returns_yaml(self, api_client):
        """Test that OpenAPI spec endpoint returns YAML."""
        response = api_client.get("/api/openapi.yaml")
        if response.status_code == 200:
            # If file exists, should be text/yaml
            assert (
                "yaml" in response.content_type.lower()
                or "text" in response.content_type.lower()
            )

    def test_post_endpoints_accept_json(self, api_client):
        """Test that POST endpoints accept application/json."""
        response = api_client.post(
            "/api/evse/current",
            data=json.dumps({"amps": 16}),
            content_type="application/json",
        )
        assert response.status_code == 200


class TestOpenAPIExamples:
    """Test examples from the OpenAPI specification."""

    def test_example_enable_and_set_current(self, api_client):
        """Test the example workflow from the spec: enable and set current."""
        # Enable EVSE
        response = api_client.post("/api/evse/enable")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Set current to 16A
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

    def test_example_connect_ev_and_charge(self, api_client):
        """Test the example workflow: connect EV and charge."""
        # Connect EV
        response = api_client.post("/api/ev/connect")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was connected
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["connected"] is True

        # Set battery SoC
        response = api_client.post(
            "/api/ev/soc", data=json.dumps({"soc": 20}), content_type="application/json"
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Verify it was set
        status = api_client.get("/api/ev/status")
        status_data = json.loads(status.data)
        assert status_data["soc"] == 20

    def test_example_trigger_and_clear_error(self, api_client):
        """Test the example workflow: trigger and clear error."""
        # Trigger GFCI error
        response = api_client.post(
            "/api/errors/trigger",
            data=json.dumps({"error": "gfci"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

        # Clear errors
        response = api_client.post("/api/errors/clear")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True


class TestSpecMatchesImplementation:
    """Guard against the spec and the code drifting apart."""

    def test_documented_response_fields_are_actually_returned(
        self, api_client, openapi_spec
    ):
        """
        A declared 200 body must match what the endpoint really sends.

        Generated clients are built from the spec, so a response that quietly
        carries more or fewer fields than declared breaks them.
        """
        cases = [
            ("/api/ev/charge_limit", {"charge_limit_soc": 80}),
            ("/api/ev/range", {"range_km_at_full": 400}),
        ]

        for path, body in cases:
            schema = openapi_spec["paths"][path]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            documented = set(schema.get("properties", {}))

            response = api_client.post(path, json=body)
            assert response.status_code == 200, path

            assert set(json.loads(response.data)) == documented, path

    def test_declared_range_minimum_matches_validation(self, api_client, openapi_spec):
        """The spec excludes 0, so the implementation must reject it too."""
        schema = openapi_spec["paths"]["/api/ev/range"]["post"]["requestBody"][
            "content"
        ]["application/json"]["schema"]["properties"]["range_km_at_full"]

        assert schema.get("exclusiveMinimum") is True
        assert (
            api_client.post("/api/ev/range", json={"range_km_at_full": 0}).status_code
            == 400
        )

    def test_nullable_reporting_fields_are_declared_nullable(self, openapi_spec):
        """
        Every field that can come back null must say so in the schema.

        Reporting is disabled by default, so an unconfigured emulator returns
        null for the target it has not been given yet. A generated client
        built from a non-nullable schema would reject that valid response.
        Checked against the real default config rather than a hardcoded list,
        so a future nullable option cannot slip through.
        """
        from src.emulator.config import default_config

        schema = openapi_spec["components"]["schemas"]["ReportingConfig"]
        reporting = default_config()["reporting"]

        for section in ("http", "mqtt"):
            properties = schema["properties"][section]["properties"]
            for key, value in reporting[section].items():
                if value is None:
                    assert properties[key].get("nullable") is True, (
                        f"reporting.{section}.{key} defaults to null but is "
                        f"not declared nullable"
                    )

"""Engine-mode plumbing that needs no firmware: locating the binary, the
config switches, and routing the web API's fault injection to the board."""

import json
import stat
from unittest.mock import MagicMock

import pytest

from src.emulator.config import apply_env_overrides, default_config
from src.emulator.engine import find_firmware
from src.emulator.evse import EVSEStateMachine
from src.web.api import WebAPI


def _fake_binary(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("OPENEVSE_NATIVE_BINARY", raising=False)
    monkeypatch.delenv("OPENEVSE_NATIVE_DIR", raising=False)
    # Keep a developer's sibling open_evse build out of these tests.
    monkeypatch.setattr("src.emulator.engine._SIBLING_CHECKOUT", "/nonexistent")


def test_finds_the_docker_layout(tmp_path, monkeypatch):
    oev6 = _fake_binary(tmp_path / "native_oev6")
    nxt = _fake_binary(tmp_path / "native_nxt")
    monkeypatch.setenv("OPENEVSE_NATIVE_DIR", str(tmp_path))
    assert find_firmware("oev6") == oev6
    assert find_firmware("nxt") == nxt


def test_finds_a_copied_platformio_build_dir(tmp_path, monkeypatch):
    nxt = _fake_binary(tmp_path / "native_nxt" / "program")
    monkeypatch.setenv("OPENEVSE_NATIVE_DIR", str(tmp_path))
    assert find_firmware("nxt") == nxt


def test_board_defaults_to_oev6(tmp_path, monkeypatch):
    oev6 = _fake_binary(tmp_path / "native_oev6")
    monkeypatch.setenv("OPENEVSE_NATIVE_DIR", str(tmp_path))
    assert find_firmware() == oev6


def test_explicit_binary_only_applies_when_no_board_is_named(tmp_path, monkeypatch):
    explicit = _fake_binary(tmp_path / "mine")
    monkeypatch.setenv("OPENEVSE_NATIVE_BINARY", explicit)
    assert find_firmware() == explicit
    assert find_firmware("nxt") is None


def test_missing_or_unknown_board_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENEVSE_NATIVE_DIR", str(tmp_path))
    assert find_firmware("oev6") is None
    assert find_firmware("nosuchboard") is None


def test_env_switches_enable_engine_mode(monkeypatch):
    monkeypatch.setenv("ENGINE_ENABLED", "true")
    monkeypatch.setenv("ENGINE_BOARD", "nxt")
    config = default_config()
    apply_env_overrides(config, verbose=False)
    assert config["engine"]["enabled"] is True
    assert config["engine"]["board"] == "nxt"


class TestFaultInjectionRouting:
    """With an engine the endpoints fault the board; they must not touch the
    model, which the firmware's state would simply overwrite."""

    @pytest.fixture
    def client(self):
        self.engine = MagicMock()
        self.evse = MagicMock(wraps=EVSEStateMachine())
        api = WebAPI(self.evse, MagicMock(), engine=self.engine)
        return api.app.test_client()

    def _post(self, client, url, body=None):
        return client.post(
            url, data=json.dumps(body or {}), content_type="application/json"
        )

    @pytest.mark.parametrize(
        "error,method",
        [
            ("gfci", "trip_gfi"),
            ("no_ground", "open_ground"),
            ("stuck_relay", "weld_relay"),
            ("diode_check", "fail_diode"),
            ("over_temp", "overheat"),
            ("gfi_self_test", "break_gfi_selftest"),
        ],
    )
    def test_trigger_faults_the_board(self, client, error, method):
        assert (
            self._post(client, "/api/errors/trigger", {"error": error}).status_code
            == 200
        )
        getattr(self.engine, method).assert_called_once()
        self.evse.trigger_error.assert_not_called()

    def test_unknown_faults_are_still_refused(self, client):
        response = self._post(client, "/api/errors/trigger", {"error": "bogus"})
        assert response.status_code == 400
        self.evse.trigger_error.assert_not_called()

    def test_clear_recovers_the_firmware(self, client):
        assert self._post(client, "/api/errors/clear").status_code == 200
        self.engine.clear_faults.assert_called_once()
        self.evse.clear_errors.assert_not_called()


class TestEngineStatusForTheUI:
    """The UI decides between a firmware selector and the native version from
    the status payload, so the payload has to say which mode is running."""

    @staticmethod
    def _client(engine=None):
        from src.emulator.ev import EVSimulator

        evse = EVSEStateMachine()
        api = WebAPI(evse, EVSimulator(), engine=engine)
        return api.app.test_client(), evse

    def test_python_mode_reports_no_engine(self):
        client, _ = self._client()
        assert client.get("/api/evse/status").get_json()["engine"] is None
        assert client.get("/api/status").get_json()["evse"]["engine"] is None

    def test_engine_mode_reports_the_firmware_it_is_running(self):
        engine = MagicMock()
        engine.describe.return_value = {
            "board": "oev6",
            "firmware_version": "9.4.1.native",
            "protocol_version": "6.0.0",
        }
        client, evse = self._client(engine)
        evse.set_engine_state(0x01)
        evse.firmware_version = "9.4.1.native"

        status = client.get("/api/evse/status").get_json()
        assert status["engine"]["board"] == "oev6"
        assert status["firmware_version"] == "9.4.1.native"
        assert client.get("/api/status").get_json()["evse"]["engine"]["board"] == "oev6"

    def test_engine_mode_refuses_a_firmware_profile_change(self):
        client, evse = self._client(MagicMock())
        before = evse.firmware_version
        response = client.post(
            "/api/evse/firmware",
            data=json.dumps({"version": "8.2.3"}),
            content_type="application/json",
        )
        assert response.status_code == 409
        assert evse.firmware_version == before

    def test_python_mode_still_changes_the_profile(self):
        client, evse = self._client()
        response = client.post(
            "/api/evse/firmware",
            data=json.dumps({"version": "9.0.0"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert evse.firmware_version == "9.0.0"

    def test_page_has_the_native_version_slot(self):
        client, _ = self._client()
        with client.get("/") as response:
            html = response.get_data(as_text=True)
        assert 'id="firmware-version-native"' in html
        assert 'id="firmware-version"' in html


def test_injected_temperature_reaches_the_web_model():
    """The over-temperature button feeds the firmware a hot sensor; the UI
    should show that temperature, and go back to ambient once cleared."""
    from src.emulator.engine import FirmwareEngine
    from src.emulator.evse import AMBIENT_TEMP

    engine = FirmwareEngine(binary="unused")  # never started: no socket to write to
    evse = EVSEStateMachine()
    evse.set_engine_mode()

    engine.overheat()
    engine.mirror_into(evse)
    assert evse.get_status()["temperature_mcp"] == 95.0

    engine.cool()
    engine.mirror_into(evse)
    assert evse.get_status()["temperature_mcp"] == AMBIENT_TEMP / 10.0


class TestEngineControls:
    """In engine mode the EVSE controls go to the firmware. Changing only the
    mirror would report success and be overwritten by its next announcement."""

    @staticmethod
    def _client(command_result=(True, [])):
        engine = MagicMock()
        engine.command.return_value = command_result
        api = WebAPI(EVSEStateMachine(), MagicMock(), engine=engine)
        return api, engine, api.app.test_client()

    @staticmethod
    def _post(client, url, body=None):
        return client.post(
            url, data=json.dumps(body or {}), content_type="application/json"
        )

    @pytest.mark.parametrize(
        "url,body,command",
        [
            ("/api/evse/enable", None, "$FE"),
            ("/api/evse/disable", None, "$FS"),
            ("/api/evse/current", {"amps": 16}, "$SC 16"),
            ("/api/evse/service_level", {"level": "L1"}, "$SL 1"),
            ("/api/evse/service_level", {"level": "L2"}, "$SL 2"),
            ("/api/evse/service_level", {"level": "Auto"}, "$SL A"),
        ],
    )
    def test_controls_are_sent_to_the_firmware(self, url, body, command):
        _, engine, client = self._client()
        assert self._post(client, url, body).status_code == 200
        engine.command.assert_called_once_with(command)

    def test_a_refusal_from_the_firmware_is_an_error_not_a_success(self):
        _, _, client = self._client(command_result=(False, ["80"]))
        response = self._post(client, "/api/evse/current", {"amps": 70})
        assert response.status_code == 400
        assert response.get_json()["success"] is False
        assert response.get_json()["firmware_reply"] == ["80"]

    def test_a_service_level_change_is_not_set_on_the_mirror_directly(self):
        """The level is the firmware's: the mirror takes it from the firmware's
        report, never from the request. Setting it here would let the mirror
        and the firmware disagree about the voltage the vehicle charges at."""
        api, _, client = self._client()
        self._post(client, "/api/evse/service_level", {"level": "L1"})
        assert api.evse.service_level == "L2"
        assert api.evse.get_status()["voltage"] == 240000

    def test_the_mirror_is_not_changed_behind_the_firmwares_back(self):
        api, _, client = self._client()
        before = api.evse.commanded_current_amps
        self._post(client, "/api/evse/current", {"amps": 16})
        assert api.evse.commanded_current_amps == before

    @pytest.mark.parametrize(
        "url,method",
        [("/api/errors/clear", "clear_faults"), ("/api/evse/reset", "restart")],
    )
    def test_recovery_runs_under_the_simulation_lock(self, url, method):
        """Both restart the firmware process; the simulation thread must not be
        mid-step, writing to the socket being replaced."""
        api, engine, client = self._client()
        held = []
        getattr(engine, method).side_effect = lambda: held.append(
            api.sim_lock._is_owned()
        )
        assert self._post(client, url).status_code == 200
        assert held == [True]

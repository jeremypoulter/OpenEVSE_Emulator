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
        ],
    )
    def test_trigger_faults_the_board(self, client, error, method):
        assert (
            self._post(client, "/api/errors/trigger", {"error": error}).status_code
            == 200
        )
        getattr(self.engine, method).assert_called_once()
        self.evse.trigger_error.assert_not_called()

    def test_faults_the_firmware_cannot_model_are_refused(self, client):
        response = self._post(client, "/api/errors/trigger", {"error": "over_temp"})
        assert response.status_code == 400
        self.evse.trigger_error.assert_not_called()

    def test_clear_restores_the_board(self, client):
        assert self._post(client, "/api/errors/clear").status_code == 200
        self.engine.clear_gfi.assert_called_once()
        self.engine.close_ground.assert_called_once()
        self.engine.unweld_relay.assert_called_once()
        self.evse.clear_errors.assert_not_called()

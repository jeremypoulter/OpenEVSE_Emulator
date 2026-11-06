"""The RAPI monitor: what the serial client was last told, per command."""

from unittest.mock import MagicMock

import pytest

from src.emulator.ev import EVSimulator
from src.emulator.evse import EVSEStateMachine
from src.emulator.rapi_monitor import RapiMonitor
from src.web.api import WebAPI


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def monitor(clock):
    return RapiMonitor(clock=clock)


def _by_command(monitor):
    return {e["command"]: e for e in monitor.snapshot()}


def test_records_the_last_reply_per_command(monitor):
    monitor.record_exchange("$GS^30\r", "$OK 02 0 02 0700^17\r")
    monitor.record_exchange("$GS^30\r", "$OK 03 5 03 0540^11\r")
    entry = _by_command(monitor)["GS"]
    assert entry["response"] == "$OK 03 5 03 0540^11"
    assert entry["count"] == 2
    assert entry["kind"] == "query"
    assert entry["ok"]


def test_decodes_the_replies_clients_poll(monitor):
    monitor.record_exchange("$GS", "$OK 03 5 03 0540^11")
    monitor.record_exchange("$GG", "$OK 24000 240000^16")
    monitor.record_exchange("$GV", "$OK 9.4.1.native 6.0.0^05")
    commands = _by_command(monitor)
    assert commands["GS"]["fields"] == {
        "state": 3,
        "elapsed_sec": 5,
        "pilot_state": 3,
        "vflags": 0x540,
    }
    assert commands["GG"]["fields"] == {"current_ma": 24000, "voltage_mv": 240000}
    assert commands["GV"]["fields"]["firmware_version"] == "9.4.1.native"


def test_accepts_either_checksum_style_and_a_sequence_id(monitor):
    monitor.record_exchange("$GS:1A*B0", "$OK 01 0 01 0200:1A^3C")
    entry = _by_command(monitor)["GS"]
    assert entry["request"] == "$GS"
    assert entry["fields"]["state"] == 1


def test_a_refused_command_is_kept_but_not_decoded(monitor):
    monitor.record_exchange("$SC 999", "$NK 80^09")
    entry = _by_command(monitor)["SC"]
    assert not entry["ok"]
    assert entry["fields"] == {}
    assert entry["kind"] == "set"


def test_unknown_commands_are_recorded_with_positional_args(monitor):
    monitor.record_exchange("$G0", "$OK 0^30")
    entry = _by_command(monitor)["G0"]
    assert entry["args"] == ["0"]
    assert entry["fields"] == {}


def test_async_notifications_are_recorded_separately(monitor):
    monitor.record_async("$AT 03 03 24 0540^12\r")
    entry = _by_command(monitor)["AT"]
    assert entry["kind"] == "async"
    assert entry["request"] is None
    assert entry["fields"]["state"] == 3
    assert entry["fields"]["current_capacity"] == 24


def test_age_is_how_long_since_the_client_last_asked(monitor, clock):
    monitor.record_exchange("$GS", "$OK 01 0 01 0200^3C")
    clock.now += 12.34
    assert _by_command(monitor)["GS"]["age_sec"] == 12.3


def test_queries_come_before_async_in_a_stable_order(monitor):
    monitor.record_async("$AT 01 01 24 0200^3C")
    monitor.record_exchange("$GS", "$OK 01 0 01 0200^3C")
    monitor.record_exchange("$GG", "$OK 0 240000^16")
    assert [e["command"] for e in monitor.snapshot()] == ["GG", "GS", "AT"]


def test_ignores_what_is_not_a_command(monitor):
    monitor.record_exchange("garbage", "$NK^21")
    monitor.record_async("")
    assert monitor.snapshot() == []


def test_clear_forgets_everything(monitor):
    monitor.record_exchange("$GS", "$OK 01 0 01 0200^3C")
    monitor.clear()
    assert monitor.snapshot() == []


def test_notifies_a_listener_with_each_entry(monitor):
    seen = []
    monitor.on_record = seen.append
    monitor.record_exchange("$GS", "$OK 01 0 01 0200^3C")
    assert [e["command"] for e in seen] == ["GS"]


class TestWebAPI:
    @staticmethod
    def _client(monitor):
        api = WebAPI(EVSEStateMachine(), EVSimulator(), rapi_monitor=monitor)
        return api, api.app.test_client()

    def test_serves_the_last_values(self, monitor):
        monitor.record_exchange("$GS", "$OK 03 5 03 0540^11")
        _, client = self._client(monitor)
        data = client.get("/api/rapi/last").get_json()
        assert [c["command"] for c in data["commands"]] == ["GS"]
        assert data["commands"][0]["fields"]["state"] == 3

    def test_is_empty_without_a_monitor(self):
        _, client = self._client(None)
        assert client.get("/api/rapi/last").get_json() == {"commands": []}

    def test_streams_traffic_to_the_ui(self, monitor):
        api, _ = self._client(monitor)
        api.socketio = MagicMock()
        monitor.record_exchange("$GS", "$OK 01 0 01 0200^3C")
        event, entry = api.socketio.emit.call_args[0]
        assert event == "rapi"
        assert entry["command"] == "GS"

    def test_a_failing_stream_never_breaks_the_serial_path(self, monitor):
        api, _ = self._client(monitor)
        api.socketio = MagicMock()
        api.socketio.emit.side_effect = RuntimeError("no websocket")
        monitor.record_exchange("$GS", "$OK 01 0 01 0200^3C")  # must not raise
        assert _by_command(monitor)["GS"]["count"] == 1

"""The engine's own protocol handling, against a fake process and socket.

These need no firmware binary, so they run everywhere; tests/test_engine.py
and tests/conformance cover the same paths against the real thing.
"""

import stat
import threading
import time
from unittest.mock import MagicMock

import pytest

from src.emulator.engine import EngineError, FirmwareEngine


class FakeSocket:
    """Records every sendall, and notices if two overlap."""

    def __init__(self, delay=0.0):
        self.sent = []
        self.delay = delay
        self.active = 0
        self.overlapped = False

    def sendall(self, data):
        self.active += 1
        if self.active > 1:
            self.overlapped = True
        time.sleep(self.delay)
        self.sent.append(data.decode())
        self.active -= 1


def lines(sock):
    return [s.strip() for s in sock.sent]


# -- starting ----------------------------------------------------------------


def test_a_binary_that_cannot_run_is_an_engine_error(tmp_path):
    """No execute bit, or a build for another architecture, must surface as the
    message the emulator prints, not a traceback."""
    binary = tmp_path / "firmware"
    binary.write_text("not a program")
    binary.chmod(binary.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    with pytest.raises(EngineError, match="could not run firmware"):
        FirmwareEngine(binary=str(binary), socket_path=str(tmp_path / "s")).start()

    binary.chmod(0o755)  # executable, but not an executable format
    with pytest.raises(EngineError, match="could not run firmware"):
        FirmwareEngine(binary=str(binary), socket_path=str(tmp_path / "s")).start()


def test_an_unexpected_connect_error_is_an_engine_error(monkeypatch):
    engine = FirmwareEngine(binary="unused")
    engine.proc = MagicMock()
    refusing = MagicMock()
    refusing.connect.side_effect = PermissionError("socket path not writable")
    monkeypatch.setattr("socket.socket", lambda *a, **k: refusing)
    with pytest.raises(EngineError, match="cannot connect"):
        engine._connect(0.1)


def test_power_on_resends_inputs_that_were_dropped_before_the_socket_existed():
    """The simulation thread keeps calling apply_ev() while the firmware is
    starting; those inputs go nowhere. If the 'already sent' caches kept them,
    the first real pilot and ammeter values would be swallowed."""
    engine = FirmwareEngine(binary="unused", board="oev6")
    engine.hello = {"board": "oev6", "adc_max": "1023"}
    engine._last_band = "A"  # recorded while there was no socket
    engine._last_current_counts = 7
    engine.sock = FakeSocket()
    engine._read_version = engine._read_calibration = lambda: None

    engine._power_on(1.0)

    assert any(line.startswith("ADC PILOT_SENSE") for line in lines(engine.sock))
    assert engine._last_current_counts == -1


# -- sending -----------------------------------------------------------------


def test_concurrent_channel_writes_never_interleave():
    """Simulation, web and channel-reader threads all write to one stream
    socket, which has no message boundaries."""
    engine = FirmwareEngine(binary="unused")
    engine.sock = FakeSocket(delay=0.002)

    threads = [
        threading.Thread(target=lambda n=n: [engine._send("IN X %d" % n)] * 5)
        for n in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not engine.sock.overlapped


# -- ammeter calibration -----------------------------------------------------


@pytest.mark.parametrize(
    "scale,offset,adc_max,amps,expected",
    [
        (220, 0, 1023, 24, 109),  # OEV6
        (37, -135, 4095, 24, 645),  # NXT: mA = reading * 37 + 135
        (37, -135, 4095, 0, 0),  # the offset must not go negative
    ],
)
def test_ammeter_is_fed_through_the_firmwares_own_calibration(
    scale, offset, adc_max, amps, expected
):
    engine = FirmwareEngine(binary="unused")
    engine.hello = {"adc_max": str(adc_max)}
    engine._ammeter_scale, engine._ammeter_offset = scale, offset
    engine.sock = FakeSocket()

    engine.set_charge_current(amps)

    mid = adc_max // 2
    assert lines(engine.sock) == [
        "ADC CURRENT %d %d" % (mid + expected, mid - expected)
    ]


def test_calibration_is_read_from_the_firmware():
    engine = FirmwareEngine(binary="unused")
    engine.process_command = lambda *_: "$OK 37 -135^3E\r"
    engine._read_calibration()
    assert (engine._ammeter_scale, engine._ammeter_offset) == (37, -135)


def test_calibration_is_reread_after_the_client_changes_it():
    engine = FirmwareEngine(binary="unused")
    engine._exchange = lambda cmd, timeout: "$OK"
    engine._read_calibration = MagicMock()
    engine._process_command_locked("$SA 200 0*00", 1.0)
    engine._read_calibration.assert_called_once()

    engine._read_calibration.reset_mock()
    engine._process_command_locked("$GS*00", 1.0)
    engine._read_calibration.assert_not_called()


# -- late replies ------------------------------------------------------------


class FakeFirmware:
    """A process that answers commands after a delay, and can be told to answer
    one late -- as the firmware does while it holds RAPI for a few seconds."""

    def __init__(self, engine, state_delay=0.01, probe_delay=0.01, query_delay=0.01):
        self.engine = engine
        self.stdin = self
        self.state_delay = state_delay
        self.probe_delay = probe_delay
        self.query_delay = query_delay

    def flush(self):
        pass

    def write(self, data):
        cmd = data.decode("latin-1").strip()
        if cmd.startswith("$GV :"):
            tag = cmd.split()[1].split("*")[0].split("^")[0]
            self._reply(self.probe_delay, "$OK 9.9.9 6.0.0 %s^00" % tag)
        elif cmd.startswith("$GS"):
            self._reply(self.state_delay, "$OK 03 5 03 0540^11")
        elif cmd.startswith("$GG"):
            self._reply(self.query_delay, "$OK 24000 240000^16")

    def _reply(self, delay, line):
        threading.Timer(delay, self.engine._on_rapi, args=(line,)).start()


def test_a_late_reply_arriving_while_the_next_command_waits_is_not_its_reply():
    """$GS is answered after we gave up on it, and the straggler lands while
    the next command is still waiting -- the case that used to hand $GG the
    state reply."""
    engine = FirmwareEngine(binary="unused")
    # the firmware is busy: the straggler (0.08s) comes before anything we send
    # afterwards is answered
    engine.proc = FakeFirmware(
        engine, state_delay=0.08, probe_delay=0.2, query_delay=0.15
    )

    assert engine.process_command("$GS*B0", timeout=0.05).startswith("$NK")
    reply = engine.process_command("$GG*B2", timeout=2.0)

    assert reply == "$OK 24000 240000^16\r"
    assert engine._responses == []


def test_a_straggler_arriving_afterwards_does_not_confuse_later_commands():
    engine = FirmwareEngine(binary="unused")
    engine.proc = FakeFirmware(engine, state_delay=0.3)

    assert engine.process_command("$GS*B0", timeout=0.05).startswith("$NK")
    assert engine.process_command("$GG*B2", timeout=2.0) == "$OK 24000 240000^16\r"
    time.sleep(0.4)  # the late $GS reply lands now

    assert engine.process_command("$GG*B2", timeout=2.0) == "$OK 24000 240000^16\r"
    assert engine._responses == []


def test_resync_gives_up_if_the_firmware_never_answers():
    engine = FirmwareEngine(binary="unused")
    engine.proc = MagicMock()  # swallows writes, never replies
    engine._resync_needed = True
    assert engine.process_command("$GS*B0", timeout=0.05).startswith("$NK")
    assert engine._resync_needed  # try again next time


@pytest.mark.parametrize(
    "volts,expected_amps",
    [(240.0, 24.0), (120.0, 48.0)],
    ids=["L2", "L1"],
)
def test_the_ct_sees_the_current_the_vehicle_draws_at_its_supply_voltage(
    volts, expected_amps
):
    """5.76 kW is 24 A at 240 V but 48 A at 120 V. Assuming 240 V halves the
    current an L1 vehicle reports to the firmware."""
    engine = FirmwareEngine(binary="unused")
    engine.outputs = {"CHARGING": 1}
    engine.set_pilot_band = MagicMock()
    engine.set_charge_current = MagicMock()
    ev = MagicMock()
    ev.get_status.return_value = {"actual_charge_rate_kw": 5.76}

    engine.apply_ev(ev, volts)

    amps = engine.set_charge_current.call_args[0][0]
    assert amps == pytest.approx(expected_amps)


@pytest.mark.parametrize(
    "state,relay,expected",
    [
        (0x03, True, False),  # charging, contactor closed: normal
        (0x03, False, True),  # contactor just opened, state not yet announced
        (0x02, False, False),  # the B handshake: must not be held back
        (0x02, True, False),
    ],
)
def test_charging_without_a_contactor(state, relay, expected):
    engine = FirmwareEngine(binary="unused")
    engine.evse_state = state
    engine.outputs = {"CHARGING": 1 if relay else 0}
    assert engine.charging_without_contactor() is expected


def test_a_failed_backend_build_leaves_nothing_running(tmp_path, monkeypatch):
    """If the firmware never boots, the fixture must not leak it."""
    import copy
    import sys

    sys.path.insert(0, os_path_of("conftest"))
    import conftest as shared
    from emulator.config import load_config
    from emulator.engine import EngineError as FixtureEngineError

    config = copy.deepcopy(load_config(shared.CONFIG_PATH))
    config["serial"]["mode"] = "tcp"
    config.setdefault("engine", {}).update(
        enabled=True, binary="/bin/true", board="oev6", wait_ms=200
    )
    stopped = []
    monkeypatch.setattr(shared.Harness, "stop", lambda self: stopped.append(self.name))

    with pytest.raises(FixtureEngineError):
        shared._build(config, "oev6")  # /bin/true never opens the channel

    assert stopped == ["oev6"]


def os_path_of(name):
    import os

    return os.path.dirname(os.path.abspath(__file__))

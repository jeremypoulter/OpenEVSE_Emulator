"""RAPI behaviour that every EVSE implementation must share.

Runs against the Python state machine and the real firmware (see
tests/conftest.py). Where these agree the Python model is a faithful stand-in;
where they do not, this is the test that says so. Only what a client such as
the WiFi gateway can rely on is asserted -- not defaults like the configured
current, which legitimately differ between implementations.
"""

import re

STATE_A = 0x01
STATE_DISABLED = 0xFF


def _int(text, base=10):
    return int(text, base)


def test_version_reports_firmware_and_protocol(backend):
    reply = backend.rapi("$GV")
    assert reply.ok
    firmware, protocol = reply.args[:2]
    assert firmware
    assert re.fullmatch(r"\d+\.\d+\.\d+", protocol)


def test_unknown_command_is_refused(backend):
    assert backend.rapi("$ZZ").status == "$NK"


def test_bad_checksum_is_refused(backend):
    backend.require_strict_checksums()
    assert backend.rapi_raw("$GV^00\r").startswith("$NK")


def test_state_reply_has_the_documented_shape(backend):
    """$GS: state, elapsed time, pilot state, vflags."""
    reply = backend.rapi("$GS")
    assert reply.ok
    assert len(reply.args) >= 4
    _int(reply.args[0], 16)
    _int(reply.args[1])
    _int(reply.args[3], 16)


def test_current_capacity_limits_have_the_documented_shape(backend):
    """$GC: min, max, pilot-set and max-configured amps."""
    reply = backend.rapi("$GC")
    assert reply.ok
    low, high = _int(reply.args[0]), _int(reply.args[1])
    assert low == 6
    assert high >= 16


def test_set_current_is_read_back(backend):
    assert backend.rapi("$SC 12").ok
    reply = backend.rapi("$GE")
    assert reply.ok
    assert _int(reply.args[0]) == 12


def test_current_above_the_maximum_is_refused(backend):
    reply = backend.rapi("$SC 999")
    assert reply.status == "$NK"


def test_current_below_the_minimum_is_refused_and_reports_the_minimum(backend):
    reply = backend.rapi("$SC 2")
    assert reply.status == "$NK"
    assert _int(reply.args[0]) == 6


def test_disable_then_enable(backend):
    assert backend.rapi("$FD").ok
    assert backend.evse_state() == STATE_DISABLED

    assert backend.rapi("$FE").ok
    assert backend.evse_state() != STATE_DISABLED


def test_fault_counters_start_at_zero(backend):
    """$GF: GFI, no-ground and stuck-relay trip counts on a fresh unit."""
    reply = backend.rapi("$GF")
    assert reply.ok
    assert [_int(v, 16) for v in reply.args[:3]] == [0, 0, 0]


def test_idle_unit_is_not_charging(backend):
    backend.step(0.5)
    assert backend.evse_state() in (0x00, STATE_A)
    assert not backend.ev.connected


def test_web_api_version_matches_the_wire(backend):
    """/api/evse/version must report what $GV reports, in every mode -- in
    engine mode that is the firmware's own version, not the model's."""
    backend.step(0.2)  # the web model is refreshed by the simulation step
    firmware, protocol = backend.rapi("$GV").args[:2]
    reported = backend.api().get("/api/evse/version").get_json()
    assert reported == {"firmware": firmware, "protocol": protocol}


def test_the_monitor_reports_what_the_client_was_told(backend):
    """The last reply the serial client received is what the monitor shows,
    whichever EVSE is behind the port."""
    backend.rapi("$FD")
    state = backend.rapi("$GS")
    backend.rapi("$SC 12")

    monitored = {e["command"]: e for e in backend.emu.rapi_monitor.snapshot()}
    assert monitored["GS"]["response"] == state.raw.strip()
    assert monitored["GS"]["fields"]["state"] == 0xFF  # disabled, as the client saw
    assert monitored["SC"]["kind"] == "set"
    assert monitored["SC"]["ok"]
    assert monitored["FD"]["kind"] == "function"

    served = backend.api().get("/api/rapi/last").get_json()["commands"]
    assert {e["command"] for e in served} >= {"GS", "SC", "FD"}


def test_the_monitor_records_async_notifications(backend):
    backend.emu._send_async_message("$AT 03 03 24 0540^12\r")
    entry = {e["command"]: e for e in backend.emu.rapi_monitor.snapshot()}["AT"]
    assert entry["kind"] == "async"
    assert entry["fields"]["state"] == 3

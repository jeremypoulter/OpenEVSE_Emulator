"""Whole-system behaviour -- vehicle, EVSE and web API together -- on every
EVSE implementation.

The vehicle is the Python model in all cases; what differs is what it is
plugged into. State changes are awaited rather than assumed to be immediate,
because the firmware runs in real time and reports when it is ready.
"""

import json
import time

import pytest

STATE_A = 0x01
STATE_B = 0x02
STATE_C = 0x03
STATE_DIODE_CHECK_FAILED = 0x05
STATE_GFCI = 0x06
STATE_NO_GROUND = 0x07
STATE_STUCK_RELAY = 0x08
STATE_GFI_TEST_FAILED = 0x09
STATE_OVER_TEMPERATURE = 0x0A
STATE_DISABLED = 0xFF


# The firmware's native bench models the OEV6's ground sensing but not the
# NXT's (CGMI), so a session on the nxt board stops at "no ground". Until that
# is modelled upstream the NXT is covered by the RAPI conformance tests and the
# canary at the bottom of this file.
NXT_NO_SESSION = "native NXT bench does not model ground sensing yet (open_evse)"


@pytest.fixture
def session(backend):
    """A backend that can hold a charging session."""
    if backend.name == "nxt":
        pytest.skip(NXT_NO_SESSION)
    return backend


def _enable(backend):
    assert backend.rapi("$FE").ok
    # The firmware holds a freshly-booted unit until told otherwise; the
    # Python model has no such lock and just accepts the command.
    backend.rapi("$SB")


def _charge(backend):
    """Plug the vehicle in and get it drawing current."""
    _enable(backend)
    backend.plug_in()
    backend.wait_for(lambda: backend.evse_state() == STATE_C, what="state C")


def test_plugging_in_starts_a_charge(session):
    backend = session
    _charge(backend)
    assert backend.ev.get_status()["actual_charge_rate_kw"] > 0


def test_unplugging_returns_to_ready(session):
    backend = session
    _charge(backend)
    backend.unplug()
    backend.wait_for(lambda: backend.evse_state() == STATE_A, what="state A")


def test_disabling_stops_the_charge(session):
    backend = session
    _charge(backend)
    assert backend.rapi("$FD").ok
    backend.wait_for(
        lambda: backend.evse_state() == STATE_DISABLED, what="disabled state"
    )
    backend.wait_for(
        lambda: backend.ev.get_status()["actual_charge_rate_kw"] == 0,
        what="vehicle to stop drawing",
    )


def test_web_api_reports_the_state_a_client_sees(session):
    backend = session
    _charge(backend)

    def api_state():
        response = backend.api().get("/api/evse/status")
        assert response.status_code == 200
        return response.get_json()["state"]

    # The web model is refreshed by the simulation step, so it trails the
    # wire by a beat rather than matching it instantly.
    backend.wait_for(lambda: api_state() == STATE_C, what="API to report state C")


def test_gfi_fault_opens_the_contactor(session):
    backend = session
    """Trip the GFI through the web API. In engine mode that is the board
    faulting and the firmware deciding; in Python mode it is the model."""
    _charge(backend)
    response = backend.api().post(
        "/api/errors/trigger",
        data=json.dumps({"error": "gfci"}),
        content_type="application/json",
    )
    assert response.status_code == 200

    backend.wait_for(lambda: backend.evse_state() == STATE_GFCI, what="GFCI fault")
    backend.wait_for(
        lambda: backend.ev.get_status()["actual_charge_rate_kw"] == 0,
        what="vehicle to stop drawing",
    )


def test_missing_ground_is_a_fault(session):
    backend = session
    _enable(backend)
    backend.plug_in()
    response = backend.api().post(
        "/api/errors/trigger",
        data=json.dumps({"error": "no_ground"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    backend.wait_for(
        lambda: backend.evse_state() == STATE_NO_GROUND, what="no-ground fault"
    )


def _trigger(backend, error):
    response = backend.api().post(
        "/api/errors/trigger",
        data=json.dumps({"error": error}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.get_json()


def _stops_drawing(backend):
    backend.wait_for(
        lambda: backend.ev.get_status()["actual_charge_rate_kw"] == 0,
        what="vehicle to stop drawing",
    )


def test_over_temperature_is_a_fault(session):
    backend = session
    _charge(backend)
    _trigger(backend, "over_temp")
    backend.wait_for(
        lambda: backend.evse_state() == STATE_OVER_TEMPERATURE, what="over-temp fault"
    )
    _stops_drawing(backend)


def test_failed_diode_check_is_a_fault(session):
    backend = session
    _enable(backend)
    backend.plug_in()
    _trigger(backend, "diode_check")
    backend.wait_for(
        lambda: backend.evse_state() == STATE_DIODE_CHECK_FAILED,
        what="diode check fault",
    )


def test_failed_gfi_self_test_blocks_the_next_charge(session):
    """The self test runs as a charge starts, so breaking the detector shows
    up when the vehicle next asks for power, not before."""
    backend = session
    _enable(backend)
    _trigger(backend, "gfi_self_test")
    backend.plug_in()
    backend.wait_for(
        lambda: backend.evse_state() == STATE_GFI_TEST_FAILED,
        what="GFI self-test fault",
    )
    _stops_drawing(backend)


@pytest.mark.parametrize("ending", ["stops_asking", "unplugs"])
def test_a_normal_stop_is_not_a_stuck_relay(session, ending):
    """Opening the contactor after an ordinary charge must not read as welded.
    The firmware only calls it a second after the relay opens, so a check that
    ends the moment the state changes would miss it -- hold well past that."""
    backend = session
    _charge(backend)
    if ending == "stops_asking":
        backend.ev.requesting_charge = False
        resting = STATE_B
    else:
        backend.unplug()
        resting = STATE_A
    backend.wait_for(lambda: backend.evse_state() == resting, what="relay to open")

    deadline = time.time() + 4
    while time.time() < deadline:
        assert backend.announced_state() == resting
        backend.step()


def test_welded_relay_is_found_when_the_firmware_opens_it(session):
    """A welded contactor only shows when the firmware commands it open and
    still sees mains downstream, so on the firmware the fault appears once the
    vehicle leaves; the Python model reports it at once."""
    backend = session
    _charge(backend)
    _trigger(backend, "stuck_relay")
    backend.unplug()
    backend.wait_for(
        lambda: backend.announced_state() == STATE_STUCK_RELAY,
        timeout=40,
        what="stuck relay fault",
    )


@pytest.mark.parametrize("error", ["gfci", "no_ground", "over_temp", "diode_check"])
def test_clearing_errors_lets_charging_resume(session, error):
    """Every fault the firmware latches has to be recoverable from the UI, or
    one click on an error button would wedge the emulator until restart."""
    backend = session
    _charge(backend)
    _trigger(backend, error)
    backend.wait_for(
        lambda: backend.evse_state() not in (STATE_A, STATE_B, STATE_C),
        timeout=25,
        what="%s fault" % error,
    )

    response = backend.api().post("/api/errors/clear")
    assert response.status_code == 200

    # A restarted firmware is boot-locked again, as at power-on.
    _enable(backend)
    backend.wait_for(
        lambda: backend.evse_state() == STATE_C, timeout=30, what="charging again"
    )


def test_session_on_every_board_canary(backend, request):
    """Expected to fail on nxt today; reports XPASS once the bench models it,
    at which point NXT_NO_SESSION and the skip above can go."""
    if backend.name == "nxt":
        request.applymarker(pytest.mark.xfail(reason=NXT_NO_SESSION, strict=False))
    _enable(backend)
    backend.plug_in()
    backend.wait_for(
        lambda: backend.evse_state() == STATE_C,
        timeout=5 if backend.name == "nxt" else 20,
        what="state C",
    )

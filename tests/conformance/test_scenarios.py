"""Whole-system behaviour -- vehicle, EVSE and web API together -- on every
EVSE implementation.

The vehicle is the Python model in all cases; what differs is what it is
plugged into. State changes are awaited rather than assumed to be immediate,
because the firmware runs in real time and reports when it is ready.
"""

import json

import pytest

STATE_A = 0x01
STATE_B = 0x02
STATE_C = 0x03
STATE_GFCI = 0x06
STATE_NO_GROUND = 0x07
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

"""Engine mode: the real safety firmware standing in for the Python EVSE.

These need a natively-built firmware binary from the open_evse repository, so
they skip when one is not present. Point at it with $OPENEVSE_NATIVE_BINARY,
or build it in a sibling checkout with:

    cd ../open_evse && pio run -e native_oev6
"""

import os

import pytest

from src.emulator.engine import FirmwareEngine
from src.emulator.ev import EVSimulator
from src.emulator.evse import EVSEState, EVSEStateMachine

DEFAULT_BINARY = os.path.join(
    os.path.dirname(__file__), "..", "..", "open_evse",
    ".pio", "build", "native_oev6", "program",
)


def _binary():
    return os.environ.get("OPENEVSE_NATIVE_BINARY") or DEFAULT_BINARY


pytestmark = pytest.mark.skipif(
    not os.path.exists(_binary()),
    reason="native firmware not built; see this module's docstring",
)


@pytest.fixture
def engine(tmp_path):
    e = FirmwareEngine(
        binary=_binary(),
        eeprom=str(tmp_path / "eeprom.bin"),
        socket_path="/tmp/oevse-engine-test-%d.sock" % os.getpid(),
    )
    e.start()
    yield e
    e.stop()


def _wait(pred, timeout=20, what="condition"):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for %s" % what)


def test_engine_starts_and_identifies_itself(engine):
    assert engine.board in ("oev6", "nxt")
    assert engine.hello.get("version")
    assert engine.hello.get("adc_max")


def test_firmware_passes_its_own_post(engine):
    """The bench answers the GFI self-test, so the firmware should come up
    clean rather than latching a self-test failure."""
    _wait(lambda: engine.boot_postcode is not None, what="boot notification")
    assert engine.boot_postcode == 0x00


def test_rapi_is_answered_by_the_firmware(engine):
    """$GV goes to the firmware and its own version string comes back, not one
    this emulator made up."""
    _wait(lambda: engine.boot_postcode is not None, what="boot")
    reply = engine.process_command("$GV*C1")
    assert reply.startswith("$OK")
    assert engine.hello["version"] in reply


def test_rapi_rejects_a_bad_checksum(engine):
    """Proof the firmware is really validating: a deliberately wrong checksum
    must be refused. A passthrough that ignored framing would answer $OK."""
    _wait(lambda: engine.boot_postcode is not None, what="boot")
    assert engine.process_command("$GV*00").startswith("$NK")


def test_vehicle_drives_the_firmware_to_charging(engine):
    """The EV model plugs in and asks to charge; the firmware decides to close
    the contactor."""
    _wait(lambda: engine.boot_postcode is not None, what="boot")
    engine.process_command("$FE*AF")   # enable
    engine.process_command("$SB*B9")   # clear the boot lock

    ev = EVSimulator()
    ev.connected = True
    ev.requesting_charge = True
    # Charging only starts once the firmware offers current, so the vehicle
    # reports no draw yet; pilot state B is what it presents.
    engine.apply_ev(ev)
    _wait(lambda: engine.pilot and engine.pilot[0] == "PWM",
          what="pilot PWM")

    # Now the car starts drawing, which is pilot state C.
    ev._actual_charge_rate_kw = 7.0
    engine.apply_ev(ev)
    # Wait on the firmware's own state report, not on the relay: it closes the
    # contactor a moment before it announces the transition, so watching the
    # relay and then asserting the state races against that ordering.
    _wait(lambda: engine.evse_state == 0x03, what="firmware state C")
    assert engine.relay_closed()


def test_gfi_trip_is_the_firmwares_decision(engine):
    """Trip the GFI mid-charge; the firmware must open the contactor. Nothing
    in the emulator decides this."""
    _wait(lambda: engine.boot_postcode is not None, what="boot")
    engine.process_command("$FE*AF")
    engine.process_command("$SB*B9")

    ev = EVSimulator()
    ev.connected = True
    ev.requesting_charge = True
    engine.apply_ev(ev)
    _wait(lambda: engine.pilot and engine.pilot[0] == "PWM", what="pilot PWM")
    ev._actual_charge_rate_kw = 7.0
    engine.apply_ev(ev)
    _wait(engine.relay_closed, what="relay closed")

    engine.trip_gfi()
    _wait(lambda: engine.evse_state == 0x06, what="firmware GFCI fault state")
    assert not engine.relay_closed()


def test_state_is_mirrored_into_the_web_model(engine):
    """The web UI reads the EVSE object, so the firmware's state has to land
    there or the UI would show a stale parallel simulation."""
    _wait(lambda: engine.boot_postcode is not None, what="boot")
    engine.process_command("$FE*AF")
    engine.process_command("$SB*B9")

    ev = EVSimulator()
    ev.connected = True
    ev.requesting_charge = True
    engine.apply_ev(ev)
    _wait(lambda: engine.evse_state == 0x02, what="firmware state B")

    evse = EVSEStateMachine()
    engine.mirror_into(evse)
    assert evse.get_status()["state"] == EVSEState.STATE_B_CONNECTED

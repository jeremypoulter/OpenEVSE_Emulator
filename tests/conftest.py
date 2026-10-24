"""Shared fixtures: run one test against every EVSE implementation.

The emulator can stand in for an OpenEVSE three ways -- the Python state
machine, or the real safety firmware built natively for either supported
board. A test that takes the ``backend`` fixture runs once against each, so
behaviour that is supposed to be the same is checked to be the same, and the
Python model is held to what the firmware actually does.

    pytest                         every backend that is available
    pytest --backend python        just the Python EVSE (no firmware needed)
    pytest --backend oev6          just the firmware built for the OEV6 board
    pytest -m "not engine"         everything that needs no firmware

The engine backends need the native firmware, found as described in
``emulator.engine.find_firmware`` (``$OPENEVSE_NATIVE_DIR``, or a sibling
open_evse checkout). Without it they skip -- unless ``OPENEVSE_REQUIRE_ENGINE``
is set, as it is in CI, where a missing binary must fail the build rather than
quietly turn it green.
"""

import copy
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from emulator.config import load_config  # noqa: E402
from emulator.engine import BOARD_ENVS, find_firmware  # noqa: E402

BACKENDS = ["python"] + sorted(BOARD_ENVS)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")


def pytest_addoption(parser):
    parser.addoption(
        "--backend",
        action="append",
        choices=BACKENDS,
        help="Run backend-parametrized tests against only this EVSE "
        "implementation (repeatable). Default: all that are available.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "engine: needs the natively-built firmware (see tests/conftest.py)"
    )


def pytest_generate_tests(metafunc):
    if "backend_name" not in metafunc.fixturenames:
        return
    chosen = metafunc.config.getoption("--backend") or BACKENDS
    params = []
    for name in BACKENDS:
        if name not in chosen:
            continue
        marks = [] if name == "python" else [pytest.mark.engine]
        params.append(pytest.param(name, id=name, marks=marks))
    metafunc.parametrize("backend_name", params)


def _xor_frame(cmd: str) -> str:
    """Frame a command with the XOR checksum both implementations accept."""
    checksum = 0
    for ch in cmd:
        checksum ^= ord(ch)
    return "%s^%02X\r" % (cmd, checksum)


class Reply:
    """A parsed RAPI reply, whichever checksum style it carries."""

    def __init__(self, raw: str):
        self.raw = raw
        body = raw.strip()
        for sep in ("^", "*"):
            if sep in body:
                body = body.split(sep)[0]
                break
        parts = body.split()
        self.status = parts[0] if parts else ""
        self.args = parts[1:]

    @property
    def ok(self) -> bool:
        return self.status == "$OK"

    def __repr__(self):
        return "Reply(%r)" % self.raw


class Harness:
    """One emulator, driven through its public surfaces.

    Built on the real ``OpenEVSEEmulator`` so the whole wiring is under test
    -- the serial handler, the simulation step, the mirror into the web model
    -- not just the EVSE object in isolation.
    """

    def __init__(self, emulator, name):
        self.emu = emulator
        self.name = name
        self.is_engine = emulator.engine is not None
        self._sim_stop = threading.Event()
        self._sim_thread = None

    # -- the wire ----------------------------------------------------------

    def rapi(self, cmd: str) -> Reply:
        """Send a command as a client on the serial port would."""
        return Reply(self.emu._handle_serial_data(_xor_frame(cmd)))

    def rapi_raw(self, framed: str) -> str:
        """Send an already-framed command, bad checksums and all."""
        return self.emu._handle_serial_data(framed)

    def require_strict_checksums(self) -> None:
        """Make checksum validation as strict as the firmware's. The Python
        handler is lenient by default, for clients that get it wrong."""
        if not self.is_engine:
            self.emu.rapi.strict_checksum = True

    # -- the world ---------------------------------------------------------

    @property
    def ev(self):
        return self.emu.ev

    def api(self):
        return self.emu.web_api.app.test_client()

    def start_simulation(self) -> None:
        """Run the simulation in its own thread, as the real emulator does.

        The firmware blocks in places -- waiting for the current to fall
        before opening a contactor, say -- and what it waits on is the
        ammeter this simulation feeds. Stepping only between RAPI calls would
        deadlock there, with the test blocked in a command and nothing
        advancing the vehicle.
        """
        self.emu.last_update_time = time.time()

        def run():
            while not self._sim_stop.is_set():
                self.emu.catch_up()
                time.sleep(0.05)

        self._sim_thread = threading.Thread(target=run, daemon=True)
        self._sim_thread.start()

    def step(self, seconds: float = 0.1) -> None:
        """Let the simulation move on. The Python EVSE is stepped by hand, so
        a test is deterministic; the firmware runs in real time on its own
        clock, so there it is enough to give it a moment."""
        if self.is_engine:
            time.sleep(0.05)
        else:
            self.emu.advance(seconds)

    def wait_for(self, pred, timeout: float = 20.0, what: str = "condition") -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred():
                return
            self.step()
        raise AssertionError("timed out waiting for %s on %s" % (what, self.name))

    def evse_state(self) -> int:
        """The EVSE state as a client sees it: the first argument of $GS."""
        reply = self.rapi("$GS")
        assert reply.ok, reply
        return int(reply.args[0], 16)

    def announced_state(self) -> int:
        """The EVSE state as the unit announces it (the async $AT), rather than
        as polled. Slow detections -- a welded contactor takes the firmware
        about 20 seconds to call -- leave it unable to answer $GS for part of
        that time, so a poll would report a timeout instead of the state."""
        if self.is_engine:
            state = self.emu.engine.evse_state
            return 0x00 if state is None else state
        return self.evse_state()

    def plug_in(self, charge: bool = True) -> None:
        self.ev.connected = True
        self.ev.requesting_charge = charge

    def unplug(self) -> None:
        self.ev.connected = False
        self.ev.requesting_charge = False

    def stop(self) -> None:
        self._sim_stop.set()
        if self._sim_thread:
            self._sim_thread.join(timeout=5)
        if self.emu.engine:
            self.emu.engine.stop()


def _build(config, name) -> Harness:
    from main import OpenEVSEEmulator

    emulator = OpenEVSEEmulator(config=config)
    harness = Harness(emulator, name)
    if emulator.engine:
        emulator.engine.start()
        harness.start_simulation()
        harness.wait_for(
            lambda: emulator.engine.boot_postcode is not None, what="firmware boot"
        )
        # Leave the unit as a fresh power-on does once the self tests pass.
        assert emulator.engine.boot_postcode == 0, "firmware POST failed on %s: %#x" % (
            name,
            emulator.engine.boot_postcode,
        )
    return harness


@pytest.fixture
def backend(backend_name, tmp_path):
    """The emulator running as the chosen implementation, idle and unplugged."""
    config = copy.deepcopy(load_config(CONFIG_PATH))
    config["serial"]["mode"] = "tcp"

    if backend_name != "python":
        binary = find_firmware(backend_name)
        if binary is None:
            message = (
                "native firmware for %s not found; build it with "
                "'pio run -e native_%s' or set $OPENEVSE_NATIVE_DIR"
                % (backend_name, backend_name)
            )
            if os.environ.get("OPENEVSE_REQUIRE_ENGINE"):
                pytest.fail(message)
            pytest.skip(message)
        config.setdefault("engine", {}).update(
            enabled=True,
            binary=binary,
            board=backend_name,
            eeprom=str(tmp_path / "eeprom.bin"),
        )

    harness = _build(config, backend_name)
    try:
        yield harness
    finally:
        harness.stop()

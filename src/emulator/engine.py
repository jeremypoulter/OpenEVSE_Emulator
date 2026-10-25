"""Engine mode: run the real OpenEVSE safety firmware instead of emulating it.

The emulator normally implements the EVSE itself -- ``evse.py`` for the state
machine, ``rapi.py`` for the protocol. Engine mode swaps those two for the
actual firmware, built natively from the open_evse repository, and keeps
everything else: the EV model, the virtual serial port, the web UI, telemetry.

What moves where:

  * RAPI comes from the firmware. Commands arriving on the virtual serial port
    are forwarded to it and its replies come back, so a client -- the ESP32
    WiFi firmware, say -- is talking to the same C++ that ships on the board.
  * The vehicle stays here. ``ev.py`` decides what the car is doing; this
    module turns that into the pilot voltage, ammeter reading and AC-sense
    levels the firmware is wired to, over its hardware control channel.
  * The board stays here too. The GFI detector follows the test coil and the
    load-side AC sense follows the contactor, because that is how the hardware
    is wired and the firmware's self-tests depend on it.

Nothing in here decides what a pilot voltage *means*. That is the firmware's
job in engine mode, and the point of running it.

The firmware is unmodified; see firmware/targets/native in the open_evse
repository for the channel protocol.
"""

import os
import re
import selectors
import socket
import subprocess
import threading
import time
from typing import Callable, Optional

# Pilot sense ADC counts per board. The firmware compares the positive peak
# against its threshold table; these sit clear of each boundary. NEG is the
# negative half of the pilot square wave and must stay below the diode-check
# threshold, or the firmware rejects the reading.
PILOT_BANDS = {
    #        A     B     C     D    NEG
    "oev6": {"A": 950, "B": 830, "C": 730, "D": 500, "NEG": 50},
    "nxt": {"A": 4000, "B": 3700, "C": 3350, "D": 2200, "NEG": 90},
}


# PlatformIO environment that builds each board's native firmware.
BOARD_ENVS = {"oev6": "native_oev6", "nxt": "native_nxt"}
DEFAULT_BOARD = "oev6"

# Where a checkout of open_evse is expected to sit next to this repository.
_SIBLING_CHECKOUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "open_evse"
)


# EVSE states the firmware latches until it is reset: vent required, then every
# fault from the diode check through over-current.
FAULT_STATES = frozenset(range(0x04, 0x0C))

# What "over temperature" presents: tenths of a degree C, past the firmware's
# panic threshold on every board.
OVERHEAT_C10 = 950


class EngineError(RuntimeError):
    """The firmware could not be started or stopped talking."""


def find_firmware(board: Optional[str] = None) -> Optional[str]:
    """Locate the natively-built firmware for a board, or None.

    Looked for, in order:

      1. ``$OPENEVSE_NATIVE_BINARY`` -- one explicit binary. Only honoured when
         no board is named, since a single path cannot serve two boards.
      2. ``$OPENEVSE_NATIVE_DIR`` -- a directory holding ``native_<board>``
         (the Docker image's layout), or ``native_<board>/program`` (a copy of
         the PlatformIO build directory).
      3. A sibling ``open_evse`` checkout built with ``pio run -e native_<board>``.
    """
    explicit = os.environ.get("OPENEVSE_NATIVE_BINARY")
    if explicit and not board:
        return explicit if os.path.exists(explicit) else None

    env_name = BOARD_ENVS.get(board or DEFAULT_BOARD)
    if env_name is None:
        return None

    candidates = []
    native_dir = os.environ.get("OPENEVSE_NATIVE_DIR")
    if native_dir:
        candidates.append(os.path.join(native_dir, env_name))
        candidates.append(os.path.join(native_dir, env_name, "program"))
    candidates.append(
        os.path.join(_SIBLING_CHECKOUT, ".pio", "build", env_name, "program")
    )
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return os.path.normpath(path)
    return None


def _rapi_frame(cmd: str) -> str:
    """Frame a RAPI command with its additive checksum: the 8-bit sum of every
    character before the '*', the leading '$' included."""
    return "%s*%02X\r" % (cmd, sum(cmd.encode()) & 0xFF)


def _reply_fields(reply: str) -> list:
    """Split a RAPI reply into its fields, dropping whichever checksum
    ('^' XOR or '*' additive) it carries."""
    return re.split(r"[\^*]", reply.strip())[0].split()


class FirmwareEngine:
    """The natively-built safety firmware, wired to a simulated board."""

    def __init__(
        self,
        binary: str,
        socket_path: Optional[str] = None,
        eeprom: Optional[str] = None,
        wait_ms: int = 10000,
        board: Optional[str] = None,
    ):
        self.binary = binary
        # AF_UNIX paths are capped near 108 bytes, so keep this short by
        # default rather than deriving it from wherever the emulator was run.
        self.socket_path = socket_path or "/tmp/openevse-engine-%d.sock" % os.getpid()
        self.eeprom = eeprom
        self.wait_ms = wait_ms
        self.board = board

        self.proc: Optional[subprocess.Popen] = None
        self.sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # One command in flight at a time: serial traffic and web requests
        # (heartbeat_status) both come through process_command().
        # Re-entrant because restart() holds it across start(), which sends
        # commands of its own.
        self._cmd_lock = threading.RLock()
        self._threads: list[threading.Thread] = []
        self._async_callback: Optional[Callable[[str], None]] = None
        self._pending_async: list = []

        self._reset_state()

    def _reset_state(self) -> None:
        """Forget everything about a firmware run: what it has told us, and
        the simulated board wired to it. A new run starts from a clean bench,
        which is also how a power cycle clears a latched fault."""
        # what the firmware has told us
        self.hello = {}
        self.outputs = {}
        self.pilot: Optional[tuple] = None
        self.evse_state: Optional[int] = None
        self.pilot_state: Optional[int] = None
        self.current_capacity: Optional[int] = None
        self.vflags: Optional[int] = None
        self.boot_postcode: Optional[int] = None
        # from $GV, so the web model can report the firmware's own versions
        self.firmware_version: Optional[str] = None
        self.protocol_version: Optional[str] = None
        self._responses = []

        # simulated board wiring
        self.gfi_detector = True
        self.ground_present = True
        self.relay_welded = False
        # The vehicle's diode is shorted or absent: the pilot's low half no
        # longer sits below the firmware's diode-check threshold.
        self.diode_failed = False
        # The detector no longer answers the test coil, so the next GFI
        # self-test (the start of a charge) fails.
        self.gfi_selftest_broken = False
        self._current_band: Optional[str] = None
        self._last_band: Optional[str] = None
        self._last_current_counts = -1

    # ------------------------------------------------------------------ life

    def start(self) -> None:
        if not os.path.exists(self.binary):
            raise EngineError(
                "firmware binary not found: %s\n"
                "Build it in the open_evse repository with:\n"
                "  pio run -e native_oev6" % self.binary
            )

        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        env = dict(os.environ)
        env["OPENEVSE_HW_SOCKET"] = self.socket_path
        env["OPENEVSE_HW_WAIT_MS"] = str(self.wait_ms)
        if self.eeprom:
            env["OPENEVSE_EEPROM"] = self.eeprom

        self.proc = subprocess.Popen(
            [self.binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            bufsize=0,
        )

        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            timeout_sec = self.wait_ms / 1000.0
            deadline = time.time() + timeout_sec
            while True:
                try:
                    self.sock.connect(self.socket_path)
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    if self.proc.poll() is not None:
                        raise EngineError(
                            "firmware exited immediately (code %s)"
                            % self.proc.returncode
                        )
                    if time.time() > deadline:
                        raise EngineError("firmware never opened %s" % self.socket_path)
                    time.sleep(0.02)

            self._spawn(self._channel_loop)
            self._spawn(self._rapi_loop)

            # The firmware waits for us before running its power-on self
            # tests, so energise the board now: ground present, contactor
            # open, pilot at +12V. Getting this in first is what lets the
            # GFI self-test pass.
            self._await(lambda: bool(self.hello), timeout_sec, "HELLO from firmware")
            if not self.board:
                self.board = self.hello.get("board", "oev6")
            if self.board not in PILOT_BANDS:
                raise EngineError("unsupported firmware board: %r" % self.board)
            self._send_aclines()
            self.set_pilot_band("A")
            self._read_version()
        except Exception:
            self._teardown()
            raise

    def _read_version(self) -> None:
        parts = _reply_fields(self.process_command(_rapi_frame("$GV")))
        if len(parts) >= 3 and parts[0] == "$OK":
            self.firmware_version, self.protocol_version = parts[1], parts[2]

    def _teardown(self) -> None:
        """Undo whatever start() managed to bring up, so a fresh start() can
        be tried again."""
        self._stop.set()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
            self.proc = None
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        for t in self._threads:
            t.join(timeout=2)
        self._threads = []
        self._pending_async = []
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        self._stop.clear()

    def stop(self) -> None:
        self._teardown()

    def _spawn(self, fn) -> None:
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        self._threads.append(t)

    def _await(self, pred, timeout, what) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if pred():
                    return
            time.sleep(0.02)
        raise EngineError("timed out waiting for %s" % what)

    # --------------------------------------------------------------- channel

    def _channel_loop(self) -> None:
        sel = selectors.DefaultSelector()
        sel.register(self.sock, selectors.EVENT_READ)
        buf = ""
        while not self._stop.is_set():
            if not sel.select(timeout=0.05):
                continue
            try:
                data = self.sock.recv(4096).decode()
            except OSError:
                return
            if not data:
                return
            buf += data
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                self._on_channel(line.strip())

    def _on_channel(self, line: str) -> None:
        if not line:
            return
        parts = line.split()
        with self._lock:
            if parts[0] == "HELLO":
                self.hello = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
                return
            if parts[0] == "PILOT":
                self.pilot = (parts[1], int(parts[2]), int(parts[3]))
                return
            if parts[0] != "OUT":
                return
            name, val = parts[1], int(parts[2])
            self.outputs[name] = val

        # React outside the lock; these write to the socket.
        if name == "GFITEST" and self.gfi_detector and not self.gfi_selftest_broken:
            # The test coil runs through the detector on real hardware, so the
            # detector follows the coil -- every self-test, not just the first,
            # and held for as long as the coil is energised so the firmware has
            # time to poll the level.
            self._send("IN GFI %d" % val)
        elif name == "CHARGING":
            self._send_aclines(charging=bool(val))

    def _send(self, line: str) -> None:
        if not self.sock:
            return
        try:
            self.sock.sendall((line + "\n").encode())
        except OSError:
            pass

    def _send_aclines(self, charging: Optional[bool] = None) -> None:
        """Drive both AC-sense lines. They are active low: voltage at the pin
        pulls it low.

        Losing earth takes both lines with it, because the sense circuits are
        ground-referenced -- and a non-CGMI board only calls bad ground when
        both pins read open, never on the ground pin alone.
        """
        if charging is None:
            charging = bool(self.outputs.get("CHARGING", 0))
        if not self.ground_present:
            self._send("IN ACLINE1 1")
            self._send("IN ACLINE2 1")
            return
        live = charging or self.relay_welded
        # Both lines sense the load side of the contactor, so with it open they
        # read dead together. Reading ACLINE2 as permanently live made every
        # open contactor look welded: the firmware calls stuck relay when
        # either line reads low a second after the relay opens.
        self._send("IN ACLINE1 %d" % (0 if live else 1))
        self._send("IN ACLINE2 %d" % (0 if live else 1))

    # ------------------------------------------------------------- the board

    def set_pilot_band(self, band: str) -> None:
        """Present the pilot as the square wave it physically is: the band's
        positive plateau paired with the negative half."""
        self._current_band = band
        if band == self._last_band:
            return
        self._last_band = band
        b = PILOT_BANDS.get(self.board or "oev6", PILOT_BANDS["oev6"])
        # With a working diode the low half sits near zero. Without one it
        # tracks the high half, which is what the firmware's check looks for.
        low = b[band] if self.diode_failed else b["NEG"]
        self._send("ADC PILOT_SENSE %d %d" % (b[band], low))

    def set_charge_current(self, amps: float) -> None:
        """Feed the ammeter. The CT is presented as a swing about mid-scale."""
        adc_max = int(self.hello.get("adc_max", 1023))
        scale = adc_max / 1023.0
        # DEFAULT_CURRENT_SCALE_FACTOR is mA per ADC count on OEV6. The bench
        # alternates the two levels on successive reads, so the firmware's
        # sum-of-squares sees a square wave, whose RMS is its full amplitude.
        # (A sine's peak would need a sqrt(2) on top of this; using one here
        # reads 41% high and trips over-current after ten seconds.)
        counts = int(amps * 1000.0 / 220.0 * scale)
        counts = max(0, min(counts, adc_max // 2 - 1))
        if counts == self._last_current_counts:
            return
        self._last_current_counts = counts
        mid = adc_max // 2
        self._send("ADC CURRENT %d %d" % (mid + counts, mid - counts))

    def relay_closed(self) -> bool:
        """Whether the firmware currently has the contactor closed."""
        with self._lock:
            return bool(self.outputs.get("CHARGING", 0))

    def apply_ev(self, ev) -> None:
        """Translate the simulated vehicle into what the firmware's inputs see."""
        self.set_pilot_band(ev.get_pilot_resistance())
        status = ev.get_status()
        rate_kw = status.get("actual_charge_rate_kw", 0.0) or 0.0
        volts = 240.0
        # No contactor, no current: the CT only sees what flows through a
        # closed relay. The vehicle may ask for power first (state C), and
        # the firmware closes the contactor in response.
        flowing = rate_kw and self.relay_closed()
        self.set_charge_current((rate_kw * 1000.0 / volts) if flowing else 0.0)

    # -- fault injection, for the web API's error-simulation endpoints ------

    def trip_gfi(self) -> None:
        self.gfi_detector = False
        self._send("IN GFI 1")

    def clear_gfi(self) -> None:
        self._send("IN GFI 0")
        self.gfi_detector = True

    def open_ground(self) -> None:
        self.ground_present = False
        self._send_aclines()

    def close_ground(self) -> None:
        self.ground_present = True
        self._send_aclines()

    def fail_diode(self) -> None:
        self.diode_failed = True
        self._resend_pilot()

    def restore_diode(self) -> None:
        self.diode_failed = False
        self._resend_pilot()

    def _resend_pilot(self) -> None:
        """Present the pilot again so a change to its low half takes effect
        without waiting for the vehicle to change state."""
        band = self._current_band
        self._last_band = None
        if band:
            self.set_pilot_band(band)

    def break_gfi_selftest(self) -> None:
        self.gfi_selftest_broken = True

    def fix_gfi_selftest(self) -> None:
        self.gfi_selftest_broken = False

    def overheat(self) -> None:
        """An enclosure sensor reads far past the panic threshold."""
        self._send("TEMP MCP9808 %d" % OVERHEAT_C10)

    def cool(self) -> None:
        self._send("TEMP MCP9808 OFF")

    def clear_faults(self) -> None:
        """Undo every injected fault, and recover the firmware if it latched.

        The firmware holds most faults until the unit is reset or power
        cycled, and the native build has no reset of its own ($FR is a no-op
        there). So when it is sitting in a fault state it is restarted, as
        pulling the power would; it boots through its self tests again and
        announces itself with $AB. Otherwise only the bench is put right.
        """
        faulted = self.evse_state in FAULT_STATES
        self.clear_gfi()
        self.close_ground()
        self.unweld_relay()
        self.restore_diode()
        self.cool()
        self.fix_gfi_selftest()
        if faulted:
            self.restart()

    def restart(self) -> None:
        """Power-cycle the firmware: a new process on the same EEPROM, so
        settings and trip counters persist as they would on a real unit."""
        with self._cmd_lock:
            self._teardown()
            self._reset_state()
            self.start()

    def weld_relay(self) -> None:
        self.relay_welded = True
        self._send_aclines(charging=True)

    def unweld_relay(self) -> None:
        self.relay_welded = False
        self._send_aclines()

    # ------------------------------------------------------------------ RAPI

    def _rapi_loop(self) -> None:
        buf = ""
        while not self._stop.is_set():
            chunk = self.proc.stdout.read(1)
            if not chunk:
                return
            # latin-1 maps every byte 0-255 to itself, unlike utf-8, which
            # would corrupt 0xFE -- RAPI's "magic space" byte.
            ch = chunk.decode("latin-1")
            if ch in ("\r", "\n"):
                if buf:
                    self._on_rapi(buf)
                    buf = ""
            else:
                buf += ch

    def _on_rapi(self, line: str) -> None:
        parts = line.split()
        if not parts:
            return

        # $AT evsestate pilotstate currentcapacity vflags
        if parts[0] == "$AT" and len(parts) >= 4:
            with self._lock:
                self.evse_state = int(parts[1], 16)
                self.pilot_state = int(parts[2], 16)
                try:
                    self.current_capacity = int(parts[3])
                except ValueError:
                    pass
                if len(parts) >= 5:
                    try:
                        self.vflags = int(parts[4], 16)
                    except ValueError:
                        pass
        elif parts[0] == "$AB" and len(parts) >= 2:
            with self._lock:
                self.boot_postcode = int(parts[1], 16)
        elif line.startswith("$OK") or line.startswith("$NK"):
            # n.b. prefix, not an exact token: a reply with no parameters has
            # its checksum hard against the code, as in "$OK^20".
            with self._lock:
                self._responses.append(line)
            return

        # Anything else the firmware volunteers is an async notification, and
        # belongs on the wire so clients see state changes as they would from
        # real hardware.
        if line.startswith("$A") or line.startswith("$WF"):
            with self._lock:
                cb = self._async_callback
                if cb is None:
                    # No client wired up yet -- keep it (notably the boot
                    # $AB) so it is not lost, and deliver it once one is.
                    self._pending_async.append(line + "\r")
                    return
            cb(line + "\r")

    def set_async_callback(self, cb: Callable[[str], None]) -> None:
        with self._lock:
            self._async_callback = cb
            pending, self._pending_async = self._pending_async, []
        for line in pending:
            cb(line)

    # The firmware can legitimately go quiet: on over-temperature it tells the
    # vehicle to pause and then holds its main loop for 5 seconds before opening
    # the contactor, answering nothing meanwhile. Waiting only that long would
    # report a timeout right at the edge, so allow comfortably longer.
    RAPI_TIMEOUT_SEC = 10.0

    def process_command(self, data: str, timeout: float = RAPI_TIMEOUT_SEC) -> str:
        """Forward a RAPI command to the firmware and return its reply.

        Signature matches RAPIHandler.process_command so the serial port does
        not need to know which is behind it.
        """
        cmd = data.strip()
        if not cmd:
            return ""

        with self._cmd_lock:
            return self._process_command_locked(cmd, timeout)

    def _process_command_locked(self, cmd: str, timeout: float) -> str:
        with self._lock:
            before = len(self._responses)

        # Pass the client's framing through untouched -- it carries their
        # checksum and any sequence id, and the firmware validates both.
        try:
            self.proc.stdin.write((cmd + "\r").encode("latin-1"))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            return "$NK^21\r"

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if len(self._responses) > before:
                    # Only one command is ever in flight -- the serial port
                    # forwards synchronously -- so the reply to this one is
                    # the first to arrive after it was sent. Consume it (and
                    # anything stale ahead of it) so the list cannot grow
                    # without bound.
                    reply = self._responses[before]
                    del self._responses[: before + 1]
                    return reply + "\r"
            time.sleep(0.005)
        return "$NK^21\r"

    def describe(self) -> dict:
        """What the web UI needs to say which firmware is running: the board
        and the version the firmware itself reported."""
        return {
            "board": self.board,
            "firmware_version": self.firmware_version,
            "protocol_version": self.protocol_version,
        }

    def heartbeat_status(self) -> Optional[dict]:
        """The firmware's heartbeat supervision state, from $GY, for the web
        API. None if the firmware does not answer."""
        parts = _reply_fields(self.process_command(_rapi_frame("$GY")))
        if len(parts) < 4 or parts[0] != "$OK":
            return None
        try:
            return {
                "interval": int(parts[1]),
                "current_limit": int(parts[2]),
                "trigger": int(parts[3]),
            }
        except ValueError:
            return None

    def clear_heartbeat_trip(self) -> None:
        """No-op: a reset does not restart the firmware, so its supervision
        state is the firmware's to keep. Present so the engine can stand in
        for RAPIHandler."""

    def send_boot_notification(self) -> None:
        """No-op: the firmware sends its own $AB when it boots, and that one is
        the truth. Present so the engine can stand in for RAPIHandler."""

    def send_state_transition(self) -> None:
        """No-op: the firmware sends its own $AT on every transition."""

    # ----------------------------------------------------------- web mirror

    def mirror_into(self, evse) -> None:
        """Push the firmware's reported state into the emulator's EVSE object,
        so the web UI shows what the firmware actually decided rather than what
        the Python state machine would have."""
        with self._lock:
            state = self.evse_state
            capacity = self.current_capacity
        if state is not None:
            evse.set_engine_state(state)
        if capacity is not None:
            evse.set_engine_capacity(capacity)
        # Report what is actually running, not the Python model's configured
        # version, which means nothing here.
        if self.firmware_version:
            evse.firmware_version = self.firmware_version
        if self.protocol_version:
            evse.protocol_version = self.protocol_version

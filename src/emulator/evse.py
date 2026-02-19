"""
EVSE (Electric Vehicle Supply Equipment) state machine.

Implements the SAE J1772 charging states and manages the charging session.
"""

import threading
import time
from typing import Callable
from enum import IntEnum

# Temperature thresholds (in 0.1°C units)
OVER_TEMP_THRESHOLD = 650  # 65.0°C
AMBIENT_TEMP = 200  # 20.0°C


class EVSEState(IntEnum):
    """EVSE states according to SAE J1772."""

    STATE_A_NOT_CONNECTED = 0x01
    STATE_B_CONNECTED = 0x02
    STATE_C_CHARGING = 0x03
    STATE_D_VENT_REQUIRED = 0x04
    STATE_SLEEP = 0xFD
    STATE_ERROR = 0xFE


class ErrorFlags(IntEnum):
    """Error condition flags."""

    GFCI_TRIP = 0x01
    STUCK_RELAY = 0x02
    NO_GROUND = 0x04
    DIODE_CHECK_FAILED = 0x08
    OVER_TEMPERATURE = 0x10
    GFI_SELF_TEST_FAILED = 0x20


class EVSEStateMachine:
    """Manages EVSE state and charging logic."""

    def __init__(
        self, firmware_version: str = "8.2.1", protocol_version: str = "5.0.1"
    ):
        """
        Initialize the EVSE state machine.

        Args:
            firmware_version: Firmware version string
            protocol_version: RAPI protocol version string
        """
        self.firmware_version = firmware_version
        self.protocol_version = protocol_version

        # EVSE state
        self._state = EVSEState.STATE_A_NOT_CONNECTED
        self._sleep_mode = False

        # Current and voltage
        self._current_capacity_amps = 32
        self._actual_current_amps = 0.0
        self._voltage_mv = 240000  # 240V in millivolts

        # Current capacity limits
        self._min_capacity_amps = 6
        self._max_hw_capacity_amps = 80
        self._pilot_capacity_amps = 32
        self._max_configured_capacity_amps = 32
        self._max_capacity_locked = False  # Lock after $SC M per spec

        # Service level
        self._service_level = "L2"  # L1, L2, or Auto

        # Temperature (in 0.1°C units)
        self._temperature_ds = 250  # 25.0°C
        self._temperature_mcp = 250

        # Session tracking
        self._session_start_time = 0
        self._session_energy_wh = 0
        self._total_energy_wh = 0

        # Error conditions
        self._error_flags = 0
        self._gfci_count = 0
        self._no_ground_count = 0
        self._stuck_relay_count = 0

        # Settings
        self._gfci_self_test = True
        self._echo_enabled = False
        self._time_limit_minutes = 0
        self._kwh_limit = 0

        # LCD Display (2x16 characters)
        self._lcd_row1 = "OpenEVSE      "
        self._lcd_row2 = "Ready         "

        # LCD Backlight color (0=OFF, 1=RED, 2=GREEN, 3=YELLOW, 4=BLUE, 5=VIOLET, 6=TEAL, 7=WHITE)
        self._lcd_backlight_color = 2  # GREEN by default (No EV Connected)

        # State change callbacks (support multiple subscribers)
        self._state_change_callbacks: list[Callable] = []

        # Thread safety
        self._lock = threading.Lock()

    def set_state_change_callback(self, callback: Callable):
        """Add callback for state changes (replaces old behavior for compatibility)."""
        self.add_state_change_callback(callback)

    def add_state_change_callback(self, callback: Callable):
        """Add callback for state changes."""
        with self._lock:
            if callback not in self._state_change_callbacks:
                self._state_change_callbacks.append(callback)

    def remove_state_change_callback(self, callback: Callable):
        """Remove callback for state changes."""
        with self._lock:
            if callback in self._state_change_callbacks:
                self._state_change_callbacks.remove(callback)

    def _notify_state_change(self, new_state: EVSEState):
        """Notify all registered callbacks of state change (call with lock held)."""
        # Make a copy of callbacks to avoid issues if modified during iteration
        callbacks = self._state_change_callbacks.copy()
        # Release lock before calling callbacks to avoid deadlock
        self._lock.release()
        try:
            for callback in callbacks:
                try:
                    callback(new_state)
                except Exception as e:
                    print(f"Error in state change callback: {e}")
        finally:
            self._lock.acquire()

    @property
    def state(self) -> EVSEState:
        """Current EVSE state."""
        with self._lock:
            if self._error_flags != 0:
                return EVSEState.STATE_ERROR
            if self._sleep_mode:
                return EVSEState.STATE_SLEEP
            return self._state

    @property
    def current_capacity_amps(self) -> int:
        """Maximum current capacity in amps."""
        with self._lock:
            return self._current_capacity_amps

    @current_capacity_amps.setter
    def current_capacity_amps(self, value: int):
        with self._lock:
            # Valid range: 6-80A for most EVSEs
            self._current_capacity_amps = max(6, min(80, value))

    @property
    def min_capacity_amps(self) -> int:
        """Minimum allowed current capacity in amps."""
        with self._lock:
            return self._min_capacity_amps

    @property
    def max_hw_capacity_amps(self) -> int:
        """Hardware maximum current capacity in amps."""
        with self._lock:
            return self._max_hw_capacity_amps

    @property
    def pilot_capacity_amps(self) -> int:
        """Current capacity advertised by pilot in amps."""
        with self._lock:
            return self._pilot_capacity_amps

    @pilot_capacity_amps.setter
    def pilot_capacity_amps(self, value: int):
        with self._lock:
            self._pilot_capacity_amps = max(
                self._min_capacity_amps, min(self._max_hw_capacity_amps, value)
            )

    @property
    def max_configured_capacity_amps(self) -> int:
        """Maximum configured current capacity in amps."""
        with self._lock:
            return self._max_configured_capacity_amps

    @max_configured_capacity_amps.setter
    def max_configured_capacity_amps(self, value: int):
        with self._lock:
            self._max_configured_capacity_amps = max(
                self._min_capacity_amps, min(self._max_hw_capacity_amps, value)
            )

    def set_current_capacity(
        self, amps: int, volatile: bool = False
    ) -> tuple[bool, int]:
        """Set current capacity, clamped to allowed range.

        Returns (ok, amps_set); ok=False when clamped.
        volatile flag is ignored in emulator (no EEPROM), present for spec parity.
        """
        with self._lock:
            allowed_max = min(
                self._max_configured_capacity_amps, self._max_hw_capacity_amps
            )
            amps_set = max(self._min_capacity_amps, min(allowed_max, amps))
            self._current_capacity_amps = amps_set
            return (amps_set == amps), amps_set

    def set_max_capacity(self, amps: int) -> tuple[bool, int]:
        """Set maximum configured capacity once (lock afterwards).

        Returns (ok, max_set). If already locked, ok=False.
        """
        with self._lock:
            if self._max_capacity_locked:
                return False, self._max_configured_capacity_amps

            max_set = max(
                self._min_capacity_amps, min(self._max_hw_capacity_amps, amps)
            )
            self._max_configured_capacity_amps = max_set
            self._max_capacity_locked = True

            # Ensure current capacity does not exceed new max
            if self._current_capacity_amps > max_set:
                self._current_capacity_amps = max_set

            return True, max_set

    @property
    def service_level(self) -> str:
        """Service level: L1, L2, or Auto."""
        with self._lock:
            return self._service_level

    @service_level.setter
    def service_level(self, value: str):
        with self._lock:
            if value in ["L1", "L2", "Auto"]:
                self._service_level = value
                # Update voltage based on service level
                if value == "L1":
                    self._voltage_mv = 120000
                elif value == "L2":
                    self._voltage_mv = 240000

    @property
    def echo_enabled(self) -> bool:
        """Whether echo mode is enabled."""
        with self._lock:
            return self._echo_enabled

    @echo_enabled.setter
    def echo_enabled(self, value: bool):
        with self._lock:
            self._echo_enabled = value

    @property
    def lcd_display(self) -> dict:
        """Get LCD display content (2x16 characters)."""
        with self._lock:
            return {
                "row1": self._lcd_row1[:16],
                "row2": self._lcd_row2[:16],
                "backlight_color": self._lcd_backlight_color,
            }

    def set_lcd_display(self, row1: str = None, row2: str = None):
        """
        Set LCD display content.

        Args:
            row1: First row (max 16 chars, padded/truncated)
            row2: Second row (max 16 chars, padded/truncated)
        """
        with self._lock:
            if row1 is not None:
                self._lcd_row1 = (row1 + " " * 16)[:16]
            if row2 is not None:
                self._lcd_row2 = (row2 + " " * 16)[:16]

    def set_lcd_text_at(self, x: int, y: int, text: str):
        """
        Set LCD display text at specific position (row, column).

        Args:
            x: Column position (0-15)
            y: Row (0-1)
            text: Text to display
        """
        with self._lock:
            if not (0 <= y <= 1 and 0 <= x <= 15):
                return

            current_row = self._lcd_row1 if y == 0 else self._lcd_row2

            # Convert 0x11 or 0xFE to space if present (both are used by different implementations)
            text_clean = text.replace("\x11", " ").replace("\xfe", " ")

            # Insert text at position x
            row_list = list(current_row)
            for i, char in enumerate(text_clean):
                if x + i < 16:
                    row_list[x + i] = char

            updated_row = "".join(row_list)

            if y == 0:
                self._lcd_row1 = updated_row
            else:
                self._lcd_row2 = updated_row

    def set_lcd_backlight_color(self, color: int):
        """
        Set LCD backlight color.

        Args:
            color: Color code (0-7)
                   0=OFF, 1=RED, 2=GREEN, 3=YELLOW, 4=BLUE, 5=VIOLET, 6=TEAL, 7=WHITE
        """
        with self._lock:
            if 0 <= color <= 7:
                self._lcd_backlight_color = color

    def enable(self) -> bool:
        """
        Enable charging (exit sleep mode).

        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if self._error_flags != 0:
                return False
            self._sleep_mode = False
            return True

    def disable(self):
        """Disable charging (enter sleep mode)."""
        with self._lock:
            self._sleep_mode = True
            self._actual_current_amps = 0.0

    def reset(self):
        """Reset the EVSE."""
        with self._lock:
            # Clear error counts but not flags (they need to be explicitly cleared)
            self._session_start_time = 0
            self._session_energy_wh = 0
            self._actual_current_amps = 0.0

    def trigger_error(self, error_flag: ErrorFlags):
        """Trigger an error condition."""
        with self._lock:
            self._trigger_error_internal(error_flag)

    def _trigger_error_internal(self, error_flag: ErrorFlags):
        """Internal method to trigger error (assumes lock is held)."""
        self._error_flags |= error_flag

        # Increment counters
        if error_flag == ErrorFlags.GFCI_TRIP:
            self._gfci_count += 1
        elif error_flag == ErrorFlags.NO_GROUND:
            self._no_ground_count += 1
        elif error_flag == ErrorFlags.STUCK_RELAY:
            self._stuck_relay_count += 1

        # Stop charging on error
        self._actual_current_amps = 0.0

        # Notify state change
        if self._state_change_callbacks:
            self._notify_state_change(EVSEState.STATE_ERROR)

    def clear_errors(self):
        """Clear all error flags."""
        with self._lock:
            # Check if we were in error state before clearing
            was_error = self._error_flags != 0
            self._error_flags = 0
            if was_error and self._state_change_callbacks:
                # Determine new state after clearing errors
                new_state = self._state
                if self._sleep_mode:
                    new_state = EVSEState.STATE_SLEEP
                self._notify_state_change(new_state)

    def update_state(self, ev_pilot_state: str):
        """
        Update EVSE state based on EV pilot signal.

        Args:
            ev_pilot_state: 'A', 'B', 'C', or 'D' from EV simulator
        """
        # Determine if we need to notify about a state change
        notify_callback = False
        new_state = None

        with self._lock:
            if self._sleep_mode:
                return

            old_state = self._state
            old_error_flags = self._error_flags

            # Update state based on pilot
            if ev_pilot_state == "A":
                # EV disconnected - clear error state
                self._error_flags = 0
                self._state = EVSEState.STATE_A_NOT_CONNECTED
                self._actual_current_amps = 0.0
                if self._session_start_time > 0:
                    # Session ended
                    self._total_energy_wh += self._session_energy_wh
                    self._session_start_time = 0
                    self._session_energy_wh = 0
            elif ev_pilot_state == "B":
                self._state = EVSEState.STATE_B_CONNECTED
                self._actual_current_amps = 0.0
            elif ev_pilot_state == "C":
                if old_state != EVSEState.STATE_C_CHARGING:
                    self._actual_current_amps = self._current_capacity_amps
                self._state = EVSEState.STATE_C_CHARGING
                if self._session_start_time == 0:
                    self._session_start_time = time.time()
            elif ev_pilot_state == "D":
                self._state = EVSEState.STATE_D_VENT_REQUIRED
                self._actual_current_amps = 0.0
                self._trigger_error_internal(ErrorFlags.DIODE_CHECK_FAILED)

            # Check if we need to notify - notify if state changed or error flags changed
            state_changed = (
                old_state != self._state or old_error_flags != self._error_flags
            )
            if state_changed and self._state_change_callbacks:
                notify_callback = True
                new_state = self._state if self._error_flags != 0 else self._state

        # Call callbacks outside of lock to avoid deadlock
        if notify_callback:
            with self._lock:
                self._notify_state_change(new_state)

    def update_charging(self, actual_charge_rate_kw: float, delta_time_sec: float):
        """
        Update charging metrics.

        Args:
            actual_charge_rate_kw: Actual charging power in kW
            delta_time_sec: Time elapsed since last update
        """
        with self._lock:
            if self._state == EVSEState.STATE_C_CHARGING:
                # Calculate actual current from power
                if self._voltage_mv > 0:
                    self._actual_current_amps = (
                        actual_charge_rate_kw * 1000.0 * 1000.0
                    ) / self._voltage_mv

                # Update energy
                energy_wh = (actual_charge_rate_kw * delta_time_sec * 1000.0) / 3600.0
                self._session_energy_wh += energy_wh

                # Simulate temperature increase during charging
                self._temperature_ds = min(
                    OVER_TEMP_THRESHOLD,
                    self._temperature_ds + int(delta_time_sec * 0.5),
                )
                self._temperature_mcp = min(
                    OVER_TEMP_THRESHOLD,
                    self._temperature_mcp + int(delta_time_sec * 0.5),
                )

                # Check for over-temperature
                if (
                    self._temperature_ds > OVER_TEMP_THRESHOLD
                    or self._temperature_mcp > OVER_TEMP_THRESHOLD
                ):
                    self._trigger_error_internal(ErrorFlags.OVER_TEMPERATURE)
            else:
                # Cool down when not charging
                self._temperature_ds = max(
                    AMBIENT_TEMP, self._temperature_ds - int(delta_time_sec * 2.0)
                )
                self._temperature_mcp = max(
                    AMBIENT_TEMP, self._temperature_mcp - int(delta_time_sec * 2.0)
                )

    def get_status(self) -> dict:
        """
        Get comprehensive EVSE status.

        Returns:
            Dictionary containing EVSE status
        """
        with self._lock:
            elapsed_time = 0
            if self._session_start_time > 0:
                elapsed_time = int(time.time() - self._session_start_time)

            # Determine current state (without calling property which would deadlock)
            current_state = self._state
            if self._error_flags != 0:
                current_state = EVSEState.STATE_ERROR
            elif self._sleep_mode:
                current_state = EVSEState.STATE_SLEEP

            return {
                "state": int(current_state),
                "state_name": current_state.name,
                "current_capacity": self._current_capacity_amps,
                "actual_current": round(self._actual_current_amps, 1),
                "voltage": self._voltage_mv,
                "temperature_ds": self._temperature_ds / 10.0,
                "temperature_mcp": self._temperature_mcp / 10.0,
                "session_energy_wh": round(self._session_energy_wh),
                "total_energy_wh": round(self._total_energy_wh),
                "session_time": elapsed_time,
                "service_level": self._service_level,
                "error_flags": self._error_flags,
                "gfci_count": self._gfci_count,
                "no_ground_count": self._no_ground_count,
                "stuck_relay_count": self._stuck_relay_count,
                "firmware_version": self.firmware_version,
                "protocol_version": self.protocol_version,
                "lcd_row1": self._lcd_row1,
                "lcd_row2": self._lcd_row2,
                "lcd_backlight_color": self._lcd_backlight_color,
            }

    def get_vflags(self) -> int:
        """
        Calculate vflags for RAPI status response.

        Returns:
            vflags value including error flags and ECVF state flags based on EVSE internal state
        """
        with self._lock:
            vflags = self._error_flags  # Start with error flags

            # Add ECVF_EV_CONNECTED if EV is connected (states B or C)
            if self._state in (EVSEState.STATE_B_CONNECTED, EVSEState.STATE_C_CHARGING):
                vflags |= 0x0100  # ECVF_EV_CONNECTED

            # Add ECVF_CHARGING_ON if EV is charging (state C)
            if self._state == EVSEState.STATE_C_CHARGING:
                vflags |= 0x0040  # ECVF_CHARGING_ON

            return vflags

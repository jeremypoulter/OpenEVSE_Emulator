"""
Electric Vehicle (EV) simulator.

Simulates an electric vehicle's behavior including battery state of charge,
charging acceptance, and connection state.
"""

import random
import threading
import time

# Charging curve constants
TAPER_START_SOC = 80.0  # SoC percentage where charging starts to taper
TAPER_RANGE = 20.0  # SoC range for tapering (80-100%)
MAX_TAPER_FACTOR = 0.5  # Maximum power reduction during taper (50%)

# Variance constants
VARIANCE_INTERVAL_SEC = 1.0  # How often to update variance
DIRECT_VARIANCE_RANGE = 0.01  # +/- 1% in direct mode
BATTERY_VARIANCE_RANGE = 0.01  # -1% in battery mode


class EVSimulator:
    """Simulates an electric vehicle."""

    def __init__(
        self, battery_capacity_kwh: float = 75.0, max_charge_rate_kw: float = 7.2
    ):
        """
        Initialize the EV simulator.

        Args:
            battery_capacity_kwh: Total battery capacity in kWh
            max_charge_rate_kw: Maximum charging rate in kW
        """
        self.battery_capacity_kwh = battery_capacity_kwh
        self.max_charge_rate_kw = max_charge_rate_kw

        # Connection state
        self._connected = False
        self._requesting_charge = False

        # Battery state
        self._soc = 50.0  # State of charge percentage (0-100)

        # Charging state
        self._actual_charge_rate_kw = 0.0

        # Error modes
        self._diode_check_failed = False

        # Direct control mode
        self._direct_mode = False
        self._direct_current_amps = 0.0

        # Current variance
        self._current_variance_enabled = False
        self._variance_multiplier = 1.0
        self._last_variance_time = time.time()

        # Thread safety
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        """Whether the EV is connected to the EVSE."""
        with self._lock:
            return self._connected

    @connected.setter
    def connected(self, value: bool):
        with self._lock:
            self._connected = value
            if not value:
                self._requesting_charge = False
                self._actual_charge_rate_kw = 0.0

    @property
    def requesting_charge(self) -> bool:
        """Whether the EV is requesting to charge."""
        with self._lock:
            return self._requesting_charge

    @requesting_charge.setter
    def requesting_charge(self, value: bool):
        with self._lock:
            if self._connected:
                self._requesting_charge = value
            else:
                self._requesting_charge = False

    @property
    def soc(self) -> float:
        """Battery state of charge percentage (0-100)."""
        with self._lock:
            return self._soc

    @soc.setter
    def soc(self, value: float):
        with self._lock:
            self._soc = max(0.0, min(100.0, value))

    @property
    def actual_charge_rate_kw(self) -> float:
        """Actual charging rate in kW."""
        with self._lock:
            return self._actual_charge_rate_kw

    @property
    def diode_check_failed(self) -> bool:
        """Whether diode check has failed."""
        with self._lock:
            return self._diode_check_failed

    @diode_check_failed.setter
    def diode_check_failed(self, value: bool):
        with self._lock:
            self._diode_check_failed = value

    @property
    def direct_mode(self) -> bool:
        """Whether direct current control mode is active."""
        with self._lock:
            return self._direct_mode

    @direct_mode.setter
    def direct_mode(self, value: bool):
        with self._lock:
            self._direct_mode = value
            self._variance_multiplier = 1.0

    @property
    def direct_current_amps(self) -> float:
        """Target current in direct control mode (amps)."""
        with self._lock:
            return self._direct_current_amps

    @direct_current_amps.setter
    def direct_current_amps(self, value: float):
        with self._lock:
            self._direct_current_amps = max(0.0, value)

    @property
    def current_variance_enabled(self) -> bool:
        """Whether random current variance is enabled."""
        with self._lock:
            return self._current_variance_enabled

    @current_variance_enabled.setter
    def current_variance_enabled(self, value: bool):
        with self._lock:
            self._current_variance_enabled = value
            self._variance_multiplier = 1.0

    def get_pilot_resistance(self) -> str:
        """
        Get the pilot resistance state according to J1772.

        Returns:
            'A' (not connected), 'B' (connected, not charging), 'C' (charging), or 'D' (error)
        """
        with self._lock:
            if not self._connected:
                return "A"

            if self._diode_check_failed:
                return "D"

            if self._requesting_charge and self._actual_charge_rate_kw > 0:
                return "C"

            return "B"

    def _update_variance(self):
        """Update the variance multiplier if enough time has elapsed."""
        now = time.time()
        if now - self._last_variance_time >= VARIANCE_INTERVAL_SEC:
            self._last_variance_time = now
            if self._direct_mode:
                # +/- 1% in direct mode
                self._variance_multiplier = 1.0 + random.uniform(
                    -DIRECT_VARIANCE_RANGE, DIRECT_VARIANCE_RANGE
                )
            else:
                # -1% in battery mode (only decrease)
                self._variance_multiplier = 1.0 - random.uniform(
                    0, BATTERY_VARIANCE_RANGE
                )

    def update_charging(
        self, offered_current_amps: float, voltage: float, delta_time_sec: float
    ):
        """
        Update the charging simulation.

        Args:
            offered_current_amps: Current offered by EVSE in amps
            voltage: Charging voltage in volts
            delta_time_sec: Time elapsed since last update in seconds
        """
        with self._lock:
            if not self._connected or not self._requesting_charge:
                self._actual_charge_rate_kw = 0.0
                return

            if self._direct_mode:
                # Direct control mode: use set current directly
                actual_amps = self._direct_current_amps

                # Apply variance if enabled
                if self._current_variance_enabled:
                    self._update_variance()
                    actual_amps *= self._variance_multiplier

                self._actual_charge_rate_kw = (actual_amps * voltage) / 1000.0
                return

            # Battery emulation mode
            if self._soc >= 100.0:
                self._actual_charge_rate_kw = 0.0
                return

            # Calculate available power
            offered_power_kw = (offered_current_amps * voltage) / 1000.0

            # Limit to max charge rate and battery acceptance
            actual_power_kw = min(offered_power_kw, self.max_charge_rate_kw)

            # Apply charging curve (taper at high SoC)
            if self._soc > TAPER_START_SOC:
                taper_factor = (
                    1.0
                    - ((self._soc - TAPER_START_SOC) / TAPER_RANGE) * MAX_TAPER_FACTOR
                )
                actual_power_kw *= taper_factor

            # Apply variance if enabled
            if self._current_variance_enabled:
                self._update_variance()
                actual_power_kw *= self._variance_multiplier

            self._actual_charge_rate_kw = actual_power_kw

            # Update battery SoC
            energy_added_kwh = (actual_power_kw * delta_time_sec) / 3600.0
            soc_increase = (energy_added_kwh / self.battery_capacity_kwh) * 100.0
            self._soc = min(100.0, self._soc + soc_increase)

            # Stop requesting charge at 100%
            if self._soc >= 100.0:
                self._requesting_charge = False
                self._actual_charge_rate_kw = 0.0

    def get_status(self) -> dict:
        """
        Get the current EV status.

        Returns:
            Dictionary containing EV status information
        """
        with self._lock:
            return {
                "connected": self._connected,
                "requesting_charge": self._requesting_charge,
                "soc": round(self._soc, 1),
                "battery_capacity_kwh": self.battery_capacity_kwh,
                "max_charge_rate_kw": self.max_charge_rate_kw,
                "actual_charge_rate_kw": round(self._actual_charge_rate_kw, 2),
                "diode_check_failed": self._diode_check_failed,
                "direct_mode": self._direct_mode,
                "direct_current_amps": round(self._direct_current_amps, 1),
                "current_variance_enabled": self._current_variance_enabled,
            }

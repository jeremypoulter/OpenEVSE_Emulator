"""
Electric Vehicle (EV) simulator.

Simulates an electric vehicle's behavior including battery state of charge,
charging acceptance, and connection state.
"""

import threading

# Charging curve constants
TAPER_START_SOC = 80.0  # SoC percentage where charging starts to taper
TAPER_RANGE = 20.0  # SoC range for tapering (80-100%)
MAX_TAPER_FACTOR = 0.5  # Maximum power reduction during taper (50%)


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
            if not self._connected or not self._requesting_charge or self._soc >= 100.0:
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
            }

"""
RAPI (Remote API) protocol handler.

Implements the OpenEVSE RAPI command protocol for serial communication.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .evse import EVSEStateMachine
    from .ev import EVSimulator


# RAPI protocol constants
RAPI_OK_RESPONSE = "$OK"
RAPI_ERROR_RESPONSE = "$NK"
RAPI_LINE_ENDING = "\r"


class RAPIHandler:
    """Handles RAPI protocol commands and responses."""

    def __init__(self, evse: "EVSEStateMachine", ev: "EVSimulator"):
        """
        Initialize the RAPI handler.

        Args:
            evse: EVSE state machine instance
            ev: EV simulator instance
        """
        self.evse = evse
        self.ev = ev

        # Command dispatch table
        self.commands = {
            "GS": self._cmd_get_state,
            "GG": self._cmd_get_current_voltage,
            "GP": self._cmd_get_temperature,
            "GV": self._cmd_get_version,
            "GU": self._cmd_get_energy,
            "GC": self._cmd_get_current_capacity,
            "GE": self._cmd_get_settings,
            "GF": self._cmd_get_fault_counters,
            "GT": self._cmd_get_time_limit,
            "GH": self._cmd_get_kwh_limit,
            "SC": self._cmd_set_current,
            "SL": self._cmd_set_service_level,
            "SE": self._cmd_set_echo,
            "ST": self._cmd_set_time_limit,
            "SH": self._cmd_set_kwh_limit,
            "FE": self._cmd_enable,
            "FD": self._cmd_disable,
            "FR": self._cmd_reset,
            "F1": self._cmd_enable_gfci_test,
            "F0": self._cmd_disable_gfci_test,
        }

    def process_command(self, command: str) -> str:
        """
        Process a RAPI command and return response.

        Args:
            command: RAPI command string (e.g., "$GS" or "$SC 16")

        Returns:
            RAPI response string (e.g., "$OK 3 1234" or "$NK")
        """
        # Strip whitespace and line endings
        command = command.strip()

        # Commands should start with $
        if not command.startswith("$"):
            return RAPI_ERROR_RESPONSE + RAPI_LINE_ENDING

        # Remove $ prefix
        command = command[1:]

        # Split command and parameters
        parts = command.split()
        if not parts:
            return RAPI_ERROR_RESPONSE + RAPI_LINE_ENDING

        cmd_code = parts[0].upper()
        params = parts[1:] if len(parts) > 1 else []

        # Echo command if enabled
        echo = ""
        if self.evse.echo_enabled:
            echo = f"${command}\r"

        # Look up command handler
        handler = self.commands.get(cmd_code)
        if handler is None:
            return echo + RAPI_ERROR_RESPONSE + RAPI_LINE_ENDING

        try:
            response = handler(params)
            return echo + response + RAPI_LINE_ENDING
        except Exception as e:
            print(f"Error processing command {cmd_code}: {e}")
            return echo + RAPI_ERROR_RESPONSE + RAPI_LINE_ENDING

    # Query Commands

    def _cmd_get_state(self, params: list) -> str:
        """$GS - Get EVSE state."""
        status = self.evse.get_status()
        state = status["state"]
        elapsed = status["session_time"]
        return f"{RAPI_OK_RESPONSE} {state} {elapsed}"

    def _cmd_get_current_voltage(self, params: list) -> str:
        """$GG - Get real-time current and voltage."""
        status = self.evse.get_status()
        # Return in milliamps and millivolts
        current_ma = int(status["actual_current"] * 1000)
        voltage_mv = status["voltage"]
        state = status["state"]
        flags = status["error_flags"]
        return f"{RAPI_OK_RESPONSE} {current_ma} {voltage_mv} {state} {flags}"

    def _cmd_get_temperature(self, params: list) -> str:
        """$GP - Get temperature readings."""
        status = self.evse.get_status()
        # Return in 0.1°C units
        temp_ds = int(status["temperature_ds"] * 10)
        temp_mcp = int(status["temperature_mcp"] * 10)
        # Error flags (0 = no error)
        return f"{RAPI_OK_RESPONSE} {temp_ds} {temp_mcp} 0 0"

    def _cmd_get_version(self, params: list) -> str:
        """$GV - Get firmware and protocol version."""
        return f"{RAPI_OK_RESPONSE} {self.evse.firmware_version} {self.evse.protocol_version}"

    def _cmd_get_energy(self, params: list) -> str:
        """$GU - Get energy usage."""
        status = self.evse.get_status()
        # Session energy in Wh
        wh = status["session_energy_wh"]
        # Also return in watt-seconds for compatibility
        ws = wh * 3600
        return f"{RAPI_OK_RESPONSE} {wh} {ws}"

    def _cmd_get_current_capacity(self, params: list) -> str:
        """$GC - Get current capacity."""
        return f"{RAPI_OK_RESPONSE} {self.evse.current_capacity_amps}"

    def _cmd_get_settings(self, params: list) -> str:
        """$GE - Get EVSE settings."""
        status = self.evse.get_status()
        capacity = status["current_capacity"]
        flags = status["error_flags"]
        return f"{RAPI_OK_RESPONSE} {capacity} {flags}"

    def _cmd_get_fault_counters(self, params: list) -> str:
        """$GF - Get fault counters."""
        status = self.evse.get_status()
        gfci = status["gfci_count"]
        no_gnd = status["no_ground_count"]
        stuck = status["stuck_relay_count"]
        return f"{RAPI_OK_RESPONSE} {gfci} {no_gnd} {stuck}"

    def _cmd_get_time_limit(self, params: list) -> str:
        """$GT - Get time limit."""
        # Not implemented in basic version
        return "$OK 0"

    def _cmd_get_kwh_limit(self, params: list) -> str:
        """$GH - Get kWh limit."""
        # Not implemented in basic version
        return "$OK 0"

    # Control Commands

    def _cmd_set_current(self, params: list) -> str:
        """$SC <amps> - Set current capacity."""
        if not params:
            return RAPI_ERROR_RESPONSE

        try:
            amps = int(params[0])
            if amps < 6 or amps > 80:
                return RAPI_ERROR_RESPONSE
            self.evse.current_capacity_amps = amps
            return RAPI_OK_RESPONSE
        except (ValueError, IndexError):
            return RAPI_ERROR_RESPONSE

    def _cmd_set_service_level(self, params: list) -> str:
        """$SL <level> - Set service level (1=L1, 2=L2, A=Auto)."""
        if not params:
            return RAPI_ERROR_RESPONSE

        level_map = {"1": "L1", "2": "L2", "A": "Auto", "a": "Auto"}
        level = level_map.get(params[0])

        if level is None:
            return RAPI_ERROR_RESPONSE

        self.evse.service_level = level
        return RAPI_OK_RESPONSE

    def _cmd_set_echo(self, params: list) -> str:
        """$SE <0|1> - Set echo mode."""
        if not params:
            return RAPI_ERROR_RESPONSE

        try:
            enabled = int(params[0]) != 0
            self.evse.echo_enabled = enabled
            return RAPI_OK_RESPONSE
        except (ValueError, IndexError):
            return RAPI_ERROR_RESPONSE

    def _cmd_set_time_limit(self, params: list) -> str:
        """$ST <minutes> - Set time limit."""
        # Not implemented in basic version
        return RAPI_OK_RESPONSE

    def _cmd_set_kwh_limit(self, params: list) -> str:
        """$SH <kwh> - Set kWh limit."""
        # Not implemented in basic version
        return RAPI_OK_RESPONSE

    def _cmd_enable(self, params: list) -> str:
        """$FE - Enable charging (exit sleep mode)."""
        if self.evse.enable():
            return RAPI_OK_RESPONSE
        return RAPI_ERROR_RESPONSE

    def _cmd_disable(self, params: list) -> str:
        """$FD - Disable charging (sleep mode)."""
        self.evse.disable()
        return RAPI_OK_RESPONSE

    def _cmd_reset(self, params: list) -> str:
        """$FR - Reset EVSE."""
        self.evse.reset()
        return RAPI_OK_RESPONSE

    def _cmd_enable_gfci_test(self, params: list) -> str:
        """$F1 - Enable GFCI self-test."""
        return RAPI_OK_RESPONSE

    def _cmd_disable_gfci_test(self, params: list) -> str:
        """$F0 - Disable GFCI self-test."""
        return RAPI_OK_RESPONSE

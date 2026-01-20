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
RAPI_SOC = "$"  # Start of command
RAPI_CHECKSUM_PREFIX = "^"  # Checksum prefix


class RAPIHandler:
    """Handles RAPI protocol commands and responses."""

    def __init__(self, evse: "EVSEStateMachine", ev: "EVSimulator", strict_checksum: bool = False):
        """
        Initialize the RAPI handler.

        Args:
            evse: EVSE state machine instance
            ev: EV simulator instance
            strict_checksum: If True, reject commands with invalid checksums. If False (default), 
                           log warnings but process commands anyway for compatibility.
        """
        self.evse = evse
        self.ev = ev
        self.strict_checksum = strict_checksum
        self.async_callback = None  # Callback to send async messages

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
            "GA": self._cmd_get_ammeter_settings,
            "GI": self._cmd_get_mcu_id,
            "GT": self._cmd_get_time_limit,
            "GH": self._cmd_get_kwh_limit,
            "SC": self._cmd_set_current,
            "SL": self._cmd_set_service_level,
            "SE": self._cmd_set_echo,
            "ST": self._cmd_set_time_limit,
            "SH": self._cmd_set_kwh_limit,
            "SY": self._cmd_heartbeat_supervision,
            "FE": self._cmd_enable,
            "FD": self._cmd_disable,
            "FS": self._cmd_sleep,
            "FR": self._cmd_reset,
            "F1": self._cmd_enable_gfci_test,
            "F0": self._cmd_disable_gfci_test,
            "FP": self._cmd_lcd_display,
            "FB": self._cmd_lcd_backlight,
        }

        # Ammeter calibration settings
        self.ammeter_scale = 1.0
        self.ammeter_offset = 0

        # MCU ID (simulated)
        self.mcu_id = "OpenEVSE03AB12CD"

        # Heartbeat supervision settings
        self.heartbeat_interval = 0
        self.heartbeat_current_limit = 0
        self.heartbeat_missed = False

    @staticmethod
    def _calculate_checksum(data: str) -> str:
        """
        Calculate XOR checksum for RAPI protocol.

        Computes XOR of all characters in the data string and returns
        as a 2-digit hexadecimal string prefixed with '^'.

        Args:
            data: String to calculate checksum for

        Returns:
            Checksum string (e.g., "^42")
        """
        checksum = 0
        for char in data:
            checksum ^= ord(char)
        return f"{RAPI_CHECKSUM_PREFIX}{checksum:02X}"

    @staticmethod
    def _append_checksum(data: str) -> str:
        """
        Append checksum to RAPI response.

        Args:
            data: RAPI response string (without checksum)

        Returns:
            RAPI response with checksum appended
        """
        checksum = RAPIHandler._calculate_checksum(data)
        return data + checksum

    @staticmethod
    def _verify_checksum(data: str) -> bool:
        """
        Verify checksum in RAPI command.

        Args:
            data: RAPI command string with checksum (including $ prefix)

        Returns:
            True if checksum is valid, False otherwise
        """
        # Find checksum marker
        checksum_pos = data.rfind(RAPI_CHECKSUM_PREFIX)
        if checksum_pos < 0:
            # No checksum provided, consider it valid
            return True

        try:
            # Extract data before checksum and the checksum value
            # NOTE: data_part INCLUDES the $ prefix - that's how OpenEVSE calculates it
            data_part = data[:checksum_pos]
            checksum_part = data[checksum_pos + 1 : checksum_pos + 3]

            # Calculate what checksum should be (includes $ prefix)
            calculated = RAPIHandler._calculate_checksum(data_part)
            expected = f"{RAPI_CHECKSUM_PREFIX}{checksum_part}"

            return calculated == expected
        except (IndexError, ValueError):
            return False

    def process_command(self, command: str) -> str:
        """
        Process a RAPI command and return response.

        Args:
            command: RAPI command string (e.g., "$GS" or "$SC 16" or "$GS^AB")

        Returns:
            RAPI response string with checksum (e.g., "$OK 3 1234^42\r")
        """
        # Strip whitespace and line endings
        command = command.strip()

        # Commands should start with $
        if not command.startswith("$"):
            response = RAPI_ERROR_RESPONSE
            return self._append_checksum(response) + RAPI_LINE_ENDING

        # Verify checksum if present
        if not self._verify_checksum(command):
            if self.strict_checksum:
                response = RAPI_ERROR_RESPONSE
                return self._append_checksum(response) + RAPI_LINE_ENDING
            else:
                # Log warning but continue processing (lenient mode for compatibility)
                print(f"Warning: Checksum mismatch for command: {command[:50]}...")

        # Remove $ prefix and checksum (if present)
        command = command[1:]
        checksum_pos = command.rfind(RAPI_CHECKSUM_PREFIX)
        if checksum_pos >= 0:
            command = command[:checksum_pos]

        # Split command and parameters
        parts = command.split()
        if not parts:
            response = RAPI_ERROR_RESPONSE
            return self._append_checksum(response) + RAPI_LINE_ENDING

        cmd_code = parts[0].upper()
        params = parts[1:] if len(parts) > 1 else []

        # Echo command if enabled
        echo = ""
        if self.evse.echo_enabled:
            echo_cmd = RAPI_SOC + RAPI_SOC.join([cmd_code] + params)
            echo = self._append_checksum(echo_cmd) + RAPI_LINE_ENDING

        # Look up command handler
        handler = self.commands.get(cmd_code)
        if handler is None:
            response = RAPI_ERROR_RESPONSE
            return echo + self._append_checksum(response) + RAPI_LINE_ENDING

        try:
            response = handler(params)
            return echo + self._append_checksum(response) + RAPI_LINE_ENDING
        except Exception as e:
            print(f"Error processing command {cmd_code}: {e}")
            response = RAPI_ERROR_RESPONSE
            return echo + self._append_checksum(response) + RAPI_LINE_ENDING

    # Query Commands

    def _cmd_get_state(self, params: list) -> str:
        """$GS - Get EVSE state.

        Response: $OK evsestate elapsed pilotstate vflags
        evsestate(hex): EVSE state
        elapsed(dec): elapsed charge time in seconds
        pilotstate(hex): EV pilot state
        vflags(hex): ECVF_xxx flags including:
          - ECVF_EV_CONNECTED (0x0100) when EV connected (state B/C)
          - ECVF_CHARGING_ON (0x0040) when charging (state C)
          - Error flags (GFCI, stuck relay, etc)
        """
        status = self.evse.get_status()
        state = f"{status['state']:02X}"
        elapsed = status["session_time"]

        # Get pilot state from EV
        pilot_state = self.ev.get_pilot_resistance()
        pilot_map = {"A": "01", "B": "02", "C": "03", "D": "04"}
        pilot_state_hex = pilot_map.get(pilot_state, "01")

        # Calculate vflags using EVSE internal state (includes error flags and ECVF state)
        vflags_hex = f"{self.evse.get_vflags():04X}"

        return f"{RAPI_OK_RESPONSE} {state} {elapsed} {pilot_state_hex} {vflags_hex}"

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

    def _cmd_get_ammeter_settings(self, params: list) -> str:
        """$GA - Get ammeter settings (scale factor and offset)."""
        return f"{RAPI_OK_RESPONSE} {self.ammeter_scale} {self.ammeter_offset}"

    def _cmd_get_mcu_id(self, params: list) -> str:
        """$GI - Get MCU ID (simulated)."""
        return f"{RAPI_OK_RESPONSE} {self.mcu_id}"

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

    def _cmd_heartbeat_supervision(self, params: list) -> str:
        """
        $SY - Heartbeat supervision.

        $SY heartbeatinterval hearbeatcurrentlimit - Set heartbeat supervision
        $SY - Heartbeat pulse (keep-alive)
        $SY 165 - Acknowledge missed pulse (magic cookie = 0xA5)
        """
        if not params:
            # Heartbeat pulse with no parameters
            response = (
                f"{RAPI_OK_RESPONSE} {self.heartbeat_interval} "
                f"{self.heartbeat_current_limit}"
            )
            if self.heartbeat_missed:
                response += " 2"  # Missed pulse status
            else:
                response += " 0"  # No missed pulse
            return response

        try:
            first_param = int(params[0])

            if first_param == 0xA5 or first_param == 165:
                # Acknowledge missed pulse
                self.heartbeat_missed = False
                return RAPI_OK_RESPONSE
            elif len(params) >= 2:
                # Set heartbeat interval and current limit
                self.heartbeat_interval = first_param
                self.heartbeat_current_limit = int(params[1])
                response = (
                    f"{RAPI_OK_RESPONSE} {self.heartbeat_interval} "
                    f"{self.heartbeat_current_limit} 0"
                )
                return response
            else:
                return RAPI_ERROR_RESPONSE
        except (ValueError, IndexError):
            return RAPI_ERROR_RESPONSE

    def _cmd_enable(self, params: list) -> str:
        """$FE - Enable charging (exit sleep mode)."""
        if self.evse.enable():
            return RAPI_OK_RESPONSE
        return RAPI_ERROR_RESPONSE

    def _cmd_disable(self, params: list) -> str:
        """$FD - Disable charging (sleep mode)."""
        self.evse.disable()
        return RAPI_OK_RESPONSE

    def _cmd_sleep(self, params: list) -> str:
        """$FS - Sleep EVSE (same as disable)."""
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

    def _cmd_lcd_display(self, params: list) -> str:
        """
        $FP - Set LCD display content (2x16 character display).

        Format: $FP x y text
        where:
          x = column (0-15)
          y = row (0-1)
          text = text to display at position (x, y)

        OPTIONAL: character 0x11 can be used for spaces (more reliable on HD44780)

        Examples:
        $FP 0 0 OpenEVSE        - Set row 0 starting at column 0 to "OpenEVSE"
        $FP 0 1 Charging 16A    - Set row 1 starting at column 0 to "Charging 16A"
        $FP 5 0 v8.2.1          - Set row 0 starting at column 5 to "v8.2.1"
        $FP 13 0                - Clear from column 13 on row 0 (empty text)
        """
        if len(params) < 2:
            return RAPI_ERROR_RESPONSE

        try:
            x = int(params[0])  # Column
            y = int(params[1])  # Row
            text = " ".join(params[2:]) if len(params) > 2 else ""

            # Validate row and column
            if not (0 <= y <= 1 and 0 <= x <= 15):
                return RAPI_ERROR_RESPONSE

            self.evse.set_lcd_text_at(x, y, text)
            return RAPI_OK_RESPONSE

        except (ValueError, IndexError):
            return RAPI_ERROR_RESPONSE

    def _cmd_lcd_backlight(self, params: list) -> str:
        """
        $FB - Set LCD backlight color.

        Format: $FB color
        where color is:
          0 = OFF
          1 = RED
          2 = GREEN
          3 = YELLOW
          4 = BLUE
          5 = VIOLET
          6 = TEAL
          7 = WHITE

        Examples:
        $FB 7           - Set backlight to white
        $FB 2           - Set backlight to green
        $FB 0           - Turn backlight off
        """
        if not params:
            return RAPI_ERROR_RESPONSE

        try:
            color = int(params[0])

            # Validate color code (0-7)
            if not (0 <= color <= 7):
                return RAPI_ERROR_RESPONSE

            self.evse.set_lcd_backlight_color(color)
            return RAPI_OK_RESPONSE

        except (ValueError, IndexError):
            return RAPI_ERROR_RESPONSE

    # Async Notifications

    def set_async_callback(self, callback):
        """Set callback for sending async notifications."""
        self.async_callback = callback

    def send_boot_notification(self):
        """
        Send $AB boot notification.
        $AB postcode fwrev
        postcode: 00 = boot OK
        """
        msg = f"$AB 00 {self.evse.firmware_version}"
        msg_with_checksum = self._append_checksum(msg) + RAPI_LINE_ENDING
        if self.async_callback:
            self.async_callback(msg_with_checksum)
            print(f"RAPI async: {msg_with_checksum.strip()}")

    def send_state_transition(self):
        """
        Send $AT state transition notification.
        $AT evsestate pilotstate currentcapacity vflags
        """
        status = self.evse.get_status()
        evse_state = f"{status['state']:02X}"
        pilot_state = self.ev.get_pilot_resistance()
        # Convert pilot state letter to hex code for consistency
        pilot_map = {"A": "01", "B": "02", "C": "03", "D": "04"}
        pilot_state_hex = pilot_map.get(pilot_state, "01")
        current = status["current_capacity"]
        # Calculate vflags using EVSE internal state (includes error flags and ECVF state)
        vflags = f"{self.evse.get_vflags():04X}"

        msg = f"$AT {evse_state} {pilot_state_hex} {current} {vflags}"
        msg_with_checksum = self._append_checksum(msg) + RAPI_LINE_ENDING
        if self.async_callback:
            self.async_callback(msg_with_checksum)
            print(f"RAPI async: {msg_with_checksum.strip()}")

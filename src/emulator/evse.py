"""
EVSE (Electric Vehicle Supply Equipment) state machine.

Implements the SAE J1772 charging states and manages the charging session.
"""

import threading
import time
from typing import Optional, Callable
from enum import IntEnum


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
    
    def __init__(self, firmware_version: str = "8.2.1", protocol_version: str = "5.0.1"):
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
        
        # State change callback
        self._state_change_callback: Optional[Callable] = None
        
        # Thread safety
        self._lock = threading.Lock()
    
    def set_state_change_callback(self, callback: Callable):
        """Set callback for state changes."""
        self._state_change_callback = callback
    
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
            if self._state_change_callback:
                self._state_change_callback(EVSEState.STATE_ERROR)
    
    def clear_errors(self):
        """Clear all error flags."""
        with self._lock:
            old_state = self.state
            self._error_flags = 0
            if old_state == EVSEState.STATE_ERROR and self._state_change_callback:
                self._state_change_callback(self._state)
    
    def update_state(self, ev_pilot_state: str):
        """
        Update EVSE state based on EV pilot signal.
        
        Args:
            ev_pilot_state: 'A', 'B', 'C', or 'D' from EV simulator
        """
        with self._lock:
            if self._error_flags != 0 or self._sleep_mode:
                return
            
            old_state = self._state
            
            # Update state based on pilot
            if ev_pilot_state == 'A':
                self._state = EVSEState.STATE_A_NOT_CONNECTED
                self._actual_current_amps = 0.0
                if self._session_start_time > 0:
                    # Session ended
                    self._total_energy_wh += self._session_energy_wh
                    self._session_start_time = 0
                    self._session_energy_wh = 0
            elif ev_pilot_state == 'B':
                self._state = EVSEState.STATE_B_CONNECTED
                self._actual_current_amps = 0.0
            elif ev_pilot_state == 'C':
                self._state = EVSEState.STATE_C_CHARGING
                self._actual_current_amps = self._current_capacity_amps
                if self._session_start_time == 0:
                    self._session_start_time = time.time()
            elif ev_pilot_state == 'D':
                self._state = EVSEState.STATE_D_VENT_REQUIRED
                self._actual_current_amps = 0.0
                self.trigger_error(ErrorFlags.DIODE_CHECK_FAILED)
            
            # Notify state change
            if old_state != self._state and self._state_change_callback:
                self._state_change_callback(self._state)
    
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
                    self._actual_current_amps = (actual_charge_rate_kw * 1000.0 * 1000.0) / self._voltage_mv
                
                # Update energy
                energy_wh = (actual_charge_rate_kw * delta_time_sec * 1000.0) / 3600.0
                self._session_energy_wh += energy_wh
                
                # Simulate temperature increase during charging
                self._temperature_ds = min(650, self._temperature_ds + int(delta_time_sec * 0.5))
                self._temperature_mcp = min(650, self._temperature_mcp + int(delta_time_sec * 0.5))
                
                # Check for over-temperature
                if self._temperature_ds > 650 or self._temperature_mcp > 650:
                    self.trigger_error(ErrorFlags.OVER_TEMPERATURE)
            else:
                # Cool down when not charging
                self._temperature_ds = max(200, self._temperature_ds - int(delta_time_sec * 2.0))
                self._temperature_mcp = max(200, self._temperature_mcp - int(delta_time_sec * 2.0))
    
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
            
            return {
                'state': int(self.state),
                'state_name': self.state.name,
                'current_capacity': self._current_capacity_amps,
                'actual_current': round(self._actual_current_amps, 1),
                'voltage': self._voltage_mv,
                'temperature_ds': self._temperature_ds / 10.0,
                'temperature_mcp': self._temperature_mcp / 10.0,
                'session_energy_wh': round(self._session_energy_wh),
                'total_energy_wh': round(self._total_energy_wh),
                'session_time': elapsed_time,
                'service_level': self._service_level,
                'error_flags': self._error_flags,
                'gfci_count': self._gfci_count,
                'no_ground_count': self._no_ground_count,
                'stuck_relay_count': self._stuck_relay_count,
                'firmware_version': self.firmware_version,
                'protocol_version': self.protocol_version
            }

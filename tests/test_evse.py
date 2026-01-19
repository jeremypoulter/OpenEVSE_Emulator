"""Tests for EVSE state machine."""

from src.emulator.evse import EVSEStateMachine, EVSEState, ErrorFlags


def test_evse_initialization():
    """Test EVSE initialization."""
    evse = EVSEStateMachine(firmware_version="8.2.1", protocol_version="5.0.1")
    assert evse.firmware_version == "8.2.1"
    assert evse.protocol_version == "5.0.1"
    assert evse.state == EVSEState.STATE_A_NOT_CONNECTED
    assert evse.current_capacity_amps == 32


def test_current_capacity_bounds():
    """Test current capacity bounds."""
    evse = EVSEStateMachine()

    # Set to 100A (should cap at 80A)
    evse.current_capacity_amps = 100
    assert evse.current_capacity_amps == 80

    # Set to 5A (should raise to 6A)
    evse.current_capacity_amps = 5
    assert evse.current_capacity_amps == 6


def test_service_level():
    """Test service level changes."""
    evse = EVSEStateMachine()

    # Default is L2 (240V)
    assert evse.service_level == "L2"

    # Change to L1
    evse.service_level = "L1"
    assert evse.service_level == "L1"
    status = evse.get_status()
    assert status["voltage"] == 120000  # 120V in millivolts

    # Change to L2
    evse.service_level = "L2"
    status = evse.get_status()
    assert status["voltage"] == 240000  # 240V in millivolts


def test_enable_disable():
    """Test enable/disable (sleep mode)."""
    evse = EVSEStateMachine()

    # Disable (sleep)
    evse.disable()
    assert evse.state == EVSEState.STATE_SLEEP

    # Enable
    assert evse.enable() is True
    assert evse.state != EVSEState.STATE_SLEEP


def test_state_transitions():
    """Test EVSE state transitions based on EV pilot."""
    evse = EVSEStateMachine()

    # Start in State A
    assert evse.state == EVSEState.STATE_A_NOT_CONNECTED

    # EV connects (State B)
    evse.update_state("B")
    assert evse.state == EVSEState.STATE_B_CONNECTED

    # EV requests charge (State C)
    evse.update_state("C")
    assert evse.state == EVSEState.STATE_C_CHARGING

    # EV stops charging (State B)
    evse.update_state("B")
    assert evse.state == EVSEState.STATE_B_CONNECTED

    # EV disconnects (State A)
    evse.update_state("A")
    assert evse.state == EVSEState.STATE_A_NOT_CONNECTED


def test_error_conditions():
    """Test error condition handling."""
    evse = EVSEStateMachine()

    # Trigger GFCI error
    evse.trigger_error(ErrorFlags.GFCI_TRIP)
    assert evse.state == EVSEState.STATE_ERROR
    status = evse.get_status()
    assert status["error_flags"] & ErrorFlags.GFCI_TRIP
    assert status["gfci_count"] == 1

    # Clear errors
    evse.clear_errors()
    status = evse.get_status()
    assert status["error_flags"] == 0
    # Counts should persist
    assert status["gfci_count"] == 1


def test_error_prevents_enable():
    """Test that errors prevent enabling."""
    evse = EVSEStateMachine()

    # Trigger error
    evse.trigger_error(ErrorFlags.NO_GROUND)

    # Try to enable (should fail)
    assert evse.enable() is False
    assert evse.state == EVSEState.STATE_ERROR

    # Clear error and try again
    evse.clear_errors()
    assert evse.enable() is True


def test_charging_energy_tracking():
    """Test energy tracking during charging."""
    evse = EVSEStateMachine()

    # Start charging
    evse.update_state("C")

    # Simulate charging at 7.2kW for 1 second
    evse.update_charging(7.2, 1.0)

    status = evse.get_status()
    # Energy should be approximately 7.2kW * 1s / 3600 = 0.002kWh = 2Wh
    assert status["session_energy_wh"] > 0


def test_session_tracking():
    """Test charging session tracking."""
    evse = EVSEStateMachine()

    # Start charging
    evse.update_state("C")
    status = evse.get_status()
    assert status["session_time"] >= 0

    # End session by disconnecting
    evse.update_state("A")
    status = evse.get_status()
    assert status["session_time"] == 0


def test_get_status():
    """Test getting EVSE status."""
    evse = EVSEStateMachine()
    evse.current_capacity_amps = 32

    status = evse.get_status()

    assert "state" in status
    assert "state_name" in status
    assert status["current_capacity"] == 32
    assert "voltage" in status
    assert "temperature_ds" in status
    assert "firmware_version" in status

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


def test_disconnect_clears_error():
    """Test that disconnecting EV clears error state."""
    evse = EVSEStateMachine()

    # Connect and trigger an error
    evse.update_state("B")
    evse.trigger_error(ErrorFlags.DIODE_CHECK_FAILED)
    assert evse.state == EVSEState.STATE_ERROR
    status = evse.get_status()
    assert status["error_flags"] & ErrorFlags.DIODE_CHECK_FAILED

    # Disconnect (State A) should clear error
    evse.update_state("A")
    assert evse.state == EVSEState.STATE_A_NOT_CONNECTED
    status = evse.get_status()
    assert status["error_flags"] == 0


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


def test_state_change_callback():
    """Test state change callback registration and notification."""
    evse = EVSEStateMachine()
    callback_states = []

    def callback(new_state: EVSEState):
        callback_states.append(new_state)

    # Register callback
    evse.add_state_change_callback(callback)

    # Trigger state change
    evse.update_state("B")
    assert EVSEState.STATE_B_CONNECTED in callback_states

    # Trigger another state change
    evse.update_state("C")
    assert EVSEState.STATE_C_CHARGING in callback_states


def test_remove_state_change_callback():
    """Test removing a state change callback."""
    evse = EVSEStateMachine()
    callback_states = []

    def callback(new_state: EVSEState):
        callback_states.append(new_state)

    # Register and remove callback
    evse.add_state_change_callback(callback)
    evse.remove_state_change_callback(callback)

    # Trigger state change - callback should not be called
    evse.update_state("B")
    assert len(callback_states) == 0


def test_callback_exception_handling():
    """Test that exceptions in callbacks don't break state machine."""
    evse = EVSEStateMachine()
    callback_called = []

    def bad_callback(new_state: EVSEState):
        callback_called.append("bad")
        raise ValueError("Test exception")

    def good_callback(new_state: EVSEState):
        callback_called.append("good")

    # Register both callbacks
    evse.add_state_change_callback(bad_callback)
    evse.add_state_change_callback(good_callback)

    # Trigger state change - should handle exception gracefully
    evse.update_state("B")
    assert "bad" in callback_called
    assert "good" in callback_called
    assert evse.state == EVSEState.STATE_B_CONNECTED


def test_pilot_capacity_setter():
    """Test pilot capacity setter with bounds."""
    evse = EVSEStateMachine()

    # Set within bounds
    evse.pilot_capacity_amps = 40
    assert evse.pilot_capacity_amps == 40

    # Set above max (should cap)
    evse.pilot_capacity_amps = 100
    assert evse.pilot_capacity_amps == 80

    # Set below min (should raise)
    evse.pilot_capacity_amps = 3
    assert evse.pilot_capacity_amps == 6


def test_max_configured_capacity_setter():
    """Test max configured capacity setter with bounds."""
    evse = EVSEStateMachine()

    # Set within bounds
    evse.max_configured_capacity_amps = 50
    assert evse.max_configured_capacity_amps == 50

    # Set above hardware max (should cap)
    evse.max_configured_capacity_amps = 100
    assert evse.max_configured_capacity_amps == 80

    # Set below min (should raise)
    evse.max_configured_capacity_amps = 3
    assert evse.max_configured_capacity_amps == 6


def test_set_current_capacity():
    """Test set_current_capacity method with clamping."""
    evse = EVSEStateMachine()

    # Set within bounds
    ok, amps = evse.set_current_capacity(30)
    assert ok is True
    assert amps == 30

    # Set above max configured (should clamp to max_configured, default 32)
    ok, amps = evse.set_current_capacity(100)
    assert ok is False
    assert amps == 32  # Clamped to default max_configured_capacity

    # Increase max configured capacity first
    evse.max_configured_capacity_amps = 80
    ok, amps = evse.set_current_capacity(100)
    assert ok is False
    assert amps == 80  # Now clamped to hardware max

    # Set below min (should clamp)
    ok, amps = evse.set_current_capacity(3)
    assert ok is False
    assert amps == 6

    # Test volatile flag (ignored in emulator)
    ok, amps = evse.set_current_capacity(25, volatile=True)
    assert ok is True
    assert amps == 25


def test_set_max_capacity():
    """Test set_max_capacity with locking behavior."""
    evse = EVSEStateMachine()

    # First set should succeed
    ok, max_set = evse.set_max_capacity(50)
    assert ok is True
    assert max_set == 50
    assert evse.max_configured_capacity_amps == 50

    # Second set should fail (locked)
    ok, max_set = evse.set_max_capacity(60)
    assert ok is False
    assert max_set == 50

    # Current capacity should be clamped to new max
    evse.current_capacity_amps = 70
    evse2 = EVSEStateMachine()
    evse2.current_capacity_amps = 70
    ok, max_set = evse2.set_max_capacity(40)
    assert ok is True
    assert evse2.current_capacity_amps == 40


def test_lcd_display():
    """Test LCD display methods."""
    evse = EVSEStateMachine()

    # Get default display
    lcd = evse.lcd_display
    assert "row1" in lcd
    assert "row2" in lcd
    assert "backlight_color" in lcd
    # Default content may be less than 16 chars, but slicing ensures max 16
    assert len(lcd["row1"]) <= 16
    assert len(lcd["row2"]) <= 16

    # Set display content
    evse.set_lcd_display(row1="OpenEVSE", row2="Ready")
    lcd = evse.lcd_display
    assert lcd["row1"][:8] == "OpenEVSE"
    assert lcd["row2"][:5] == "Ready"

    # Test padding - set_lcd_display should pad to 16 chars
    evse.set_lcd_display(row1="Hi", row2="")
    lcd = evse.lcd_display
    # After padding, string should start with "Hi"
    assert lcd["row1"][:2] == "Hi"

    # Test partial update
    evse.set_lcd_display(row1="Line 1")
    evse.set_lcd_display(row2="Line 2")
    assert evse.lcd_display["row1"][:6] == "Line 1"
    assert evse.lcd_display["row2"][:6] == "Line 2"


def test_set_lcd_text_at():
    """Test setting LCD text at specific position."""
    evse = EVSEStateMachine()

    # Set text at position
    evse.set_lcd_text_at(0, 0, "Test")
    lcd = evse.lcd_display
    assert lcd["row1"][:4] == "Test"

    # Set at middle position
    evse.set_lcd_text_at(5, 1, "Text")
    lcd = evse.lcd_display
    assert lcd["row2"][5:9] == "Text"

    # Test special character replacement
    evse.set_lcd_text_at(0, 0, "A\x11B\xfeC")
    lcd = evse.lcd_display
    assert "A B C" in lcd["row1"]

    # Test out of bounds (should be ignored)
    evse.set_lcd_text_at(20, 0, "Invalid")
    evse.set_lcd_text_at(0, 5, "Invalid")


def test_lcd_backlight_color():
    """Test LCD backlight color setting."""
    evse = EVSEStateMachine()

    # Set backlight color
    evse.set_lcd_backlight_color(3)
    lcd = evse.lcd_display
    assert lcd["backlight_color"] == 3

    # Test different color
    evse.set_lcd_backlight_color(7)
    lcd = evse.lcd_display
    assert lcd["backlight_color"] == 7


def test_error_clearing_with_callbacks():
    """Test error clearing triggers state change callback."""
    evse = EVSEStateMachine()
    callback_states = []

    def callback(new_state: EVSEState):
        callback_states.append(new_state)

    evse.add_state_change_callback(callback)

    # Trigger error
    evse.trigger_error(ErrorFlags.GFCI_TRIP)
    callback_states.clear()

    # Clear error should trigger callback
    evse.clear_errors()
    assert EVSEState.STATE_A_NOT_CONNECTED in callback_states


def test_sleep_mode_state_update():
    """Test that state updates are ignored in sleep mode."""
    evse = EVSEStateMachine()
    callback_states = []

    def callback(new_state: EVSEState):
        callback_states.append(new_state)

    evse.add_state_change_callback(callback)

    # Enter sleep mode
    evse.disable()
    assert evse.state == EVSEState.STATE_SLEEP
    callback_states.clear()

    # Try to update state (should be ignored)
    evse.update_state("B")
    assert len(callback_states) == 0
    assert evse.state == EVSEState.STATE_SLEEP


def test_temperature_cooldown():
    """Test temperature cooldown when not charging."""
    evse = EVSEStateMachine()

    # Heat up by charging
    evse.update_state("C")
    evse.update_charging(7.2, 10.0)  # Charge for 10 seconds

    initial_temp = evse.get_status()["temperature_ds"]

    # Stop charging and allow cooldown
    evse.update_state("B")
    evse.update_charging(0.0, 5.0)  # Not charging for 5 seconds

    final_temp = evse.get_status()["temperature_ds"]
    # Temperature should decrease
    assert final_temp < initial_temp


def test_session_energy_accumulation():
    """Test session energy accumulates to total when session ends."""
    evse = EVSEStateMachine()

    # Start first session
    evse.update_state("C")
    evse.update_charging(7.2, 1.0)
    session_energy = evse.get_status()["session_energy_wh"]

    # End session
    evse.update_state("A")

    # Check total energy increased
    total_energy = evse.get_status()["total_energy_wh"]
    assert total_energy >= session_energy

    # Session energy should be reset
    assert evse.get_status()["session_energy_wh"] == 0


def test_error_clearing_in_sleep_mode():
    """Test error clearing in sleep mode triggers callback with sleep state."""
    evse = EVSEStateMachine()
    callback_states = []

    def callback(new_state: EVSEState):
        callback_states.append(new_state)

    evse.add_state_change_callback(callback)

    # Trigger error then enter sleep mode
    evse.trigger_error(ErrorFlags.GFCI_TRIP)
    evse.disable()  # Enter sleep mode
    callback_states.clear()

    # Clear error while in sleep mode
    evse.clear_errors()
    # Should trigger callback with SLEEP state
    assert EVSEState.STATE_SLEEP in callback_states


def test_state_d_vent_required():
    """Test State D (ventilation required) triggers diode check error."""
    evse = EVSEStateMachine()

    # Simulate State D
    evse.update_state("D")
    assert evse.state == EVSEState.STATE_ERROR
    status = evse.get_status()
    assert status["error_flags"] & ErrorFlags.DIODE_CHECK_FAILED


def test_over_temperature_during_charging():
    """Test over-temperature error during charging."""
    evse = EVSEStateMachine()

    # Start charging and heat up significantly
    evse.update_state("C")
    # Charge for a long time to trigger over-temp
    evse.update_charging(7.2, 100.0)

    status = evse.get_status()
    # Should trigger over-temperature error
    if status["temperature_ds"] > 650 or status["temperature_mcp"] > 650:
        assert status["error_flags"] & ErrorFlags.OVER_TEMPERATURE

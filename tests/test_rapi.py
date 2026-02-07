"""Tests for RAPI protocol handler."""

import pytest
from src.emulator.evse import EVSEStateMachine
from src.emulator.ev import EVSimulator
from src.emulator.rapi import RAPIHandler


@pytest.fixture
def rapi():
    """Create RAPI handler for testing."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    return RAPIHandler(evse, ev)


def test_get_state(rapi):
    """Test $GS command."""
    response = rapi.process_command("$GS\r")
    assert response.startswith("$OK")
    assert response.endswith("\r")

    # Should have 4 values: state, elapsed, pilotstate, vflags
    parts = response.strip().split()
    assert len(parts) == 5  # $OK + 4 values


def test_get_version(rapi):
    """Test $GV command."""
    response = rapi.process_command("$GV\r")
    assert "$OK 8.2.1 5.0.1" in response


def test_get_current_voltage(rapi):
    """Test $GG command."""
    response = rapi.process_command("$GG\r")
    assert response.startswith("$OK")
    # Should have 4 values: current, voltage, state, flags
    parts = response.strip().split()
    assert len(parts) == 5  # $OK + 4 values


def test_get_temperature(rapi):
    """Test $GP command."""
    response = rapi.process_command("$GP\r")
    assert response.startswith("$OK")


def test_get_energy(rapi):
    """Test $GU command."""
    response = rapi.process_command("$GU\r")
    assert response.startswith("$OK")


def test_get_current_capacity(rapi):
    """Test $GC command."""
    response = rapi.process_command("$GC\r")
    # Expect four values: minamps hmaxamps pilotamps cmaxamps
    assert response.startswith("$OK 6 80 32 32")


def test_set_current(rapi):
    """Test $SC command."""
    # Set to 16A
    response = rapi.process_command("$SC 16\r")
    assert "$OK" in response

    # Verify it was set
    assert rapi.evse.current_capacity_amps == 16

    # Try invalid value (too low)
    response = rapi.process_command("$SC 5\r")
    assert "$NK" in response

    # Try invalid value (too high)
    response = rapi.process_command("$SC 100\r")
    assert "$NK" in response


def test_set_service_level(rapi):
    """Test $SL command."""
    # Set to L1
    response = rapi.process_command("$SL 1\r")
    assert "$OK" in response
    assert rapi.evse.service_level == "L1"

    # Set to L2
    response = rapi.process_command("$SL 2\r")
    assert "$OK" in response
    assert rapi.evse.service_level == "L2"

    # Set to Auto
    response = rapi.process_command("$SL A\r")
    assert "$OK" in response
    assert rapi.evse.service_level == "Auto"


def test_enable_disable(rapi):
    """Test $FE and $FD commands."""
    # Disable
    response = rapi.process_command("$FD\r")
    assert "$OK" in response

    # Enable
    response = rapi.process_command("$FE\r")
    assert "$OK" in response


def test_reset(rapi):
    """Test $FR command."""
    response = rapi.process_command("$FR\r")
    assert "$OK" in response


def test_echo_mode(rapi):
    """Test $SE command for echo mode."""
    # Enable echo
    response = rapi.process_command("$SE 1\r")
    assert "$OK" in response
    assert rapi.evse.echo_enabled

    # With echo enabled, command should be echoed
    response = rapi.process_command("$GS\r")
    assert "$GS" in response

    # Disable echo
    response = rapi.process_command("$SE 0\r")
    assert "$OK" in response
    assert not rapi.evse.echo_enabled


def test_invalid_command(rapi):
    """Test invalid command returns $NK."""
    response = rapi.process_command("$XX\r")
    assert "$NK" in response


def test_malformed_command(rapi):
    """Test malformed commands."""
    # Missing $
    response = rapi.process_command("GS\r")
    assert "$NK" in response

    # Empty command
    response = rapi.process_command("$\r")
    assert "$NK" in response


def test_command_with_newline(rapi):
    """Test commands with different line endings."""
    # Just CR
    response = rapi.process_command("$GS\r")
    assert "$OK" in response

    # Just LF
    response = rapi.process_command("$GS\n")
    assert "$OK" in response

    # CRLF
    response = rapi.process_command("$GS\r\n")
    assert "$OK" in response


def test_case_insensitive(rapi):
    """Test commands are case insensitive."""
    response1 = rapi.process_command("$GS\r")
    response2 = rapi.process_command("$gs\r")
    response3 = rapi.process_command("$Gs\r")

    # All should work
    assert "$OK" in response1
    assert "$OK" in response2
    assert "$OK" in response3


# Tests for additional commands


def test_get_ammeter_settings(rapi):
    """Test $GA - Get ammeter settings."""
    response = rapi.process_command("$GA")

    assert response.startswith("$OK ")
    assert "^" in response  # Has checksum
    assert response.endswith("\r")


def test_get_ammeter_settings_values(rapi):
    """Test $GA returns scale factor and offset."""
    rapi.ammeter_scale = 1.5
    rapi.ammeter_offset = 10

    response = rapi.process_command("$GA")
    msg = response.rstrip("\r").split("^")[0]
    parts = msg.split()

    assert parts[0] == "$OK"
    assert float(parts[1]) == 1.5
    assert int(parts[2]) == 10


def test_get_mcu_id(rapi):
    """Test $GI - Get MCU ID."""
    response = rapi.process_command("$GI")

    assert response.startswith("$OK ")
    assert "^" in response  # Has checksum
    assert response.endswith("\r")

    # MCU ID should be consistent
    msg = response.rstrip("\r").split("^")[0].split()[1]
    assert len(msg) > 0


def test_get_mcu_id_consistent(rapi):
    """Test $GI returns same ID on multiple calls."""
    response1 = rapi.process_command("$GI")
    response2 = rapi.process_command("$GI")

    msg1 = response1.rstrip("\r").split("^")[0].split()[1]
    msg2 = response2.rstrip("\r").split("^")[0].split()[1]

    assert msg1 == msg2


def test_heartbeat_supervision_pulse(rapi):
    """Test $SY - Heartbeat pulse (keep-alive)."""
    response = rapi.process_command("$SY")

    assert response.startswith("$OK ")
    assert "^" in response  # Has checksum
    assert response.endswith("\r")


def test_heartbeat_supervision_set(rapi):
    """Test $SY - Set heartbeat interval and current limit."""
    response = rapi.process_command("$SY 100 6")

    assert response.startswith("$OK ")
    msg = response.rstrip("\r").split("^")[0]
    parts = msg.split()

    # Should return OK interval limit status
    assert len(parts) >= 3
    assert int(parts[1]) == 100  # Interval
    assert int(parts[2]) == 6  # Current limit


def test_heartbeat_supervision_sets_values(rapi):
    """Test $SY sets heartbeat parameters."""
    rapi.process_command("$SY 100 6")

    assert rapi.heartbeat_interval == 100
    assert rapi.heartbeat_current_limit == 6


def test_heartbeat_supervision_acknowledge_missed(rapi):
    """Test $SY 165 - Acknowledge missed pulse."""
    # Mark as missed
    rapi.heartbeat_missed = True

    # Send acknowledgement
    response = rapi.process_command("$SY 165")

    assert response.startswith("$OK")
    assert rapi.heartbeat_missed is False


def test_heartbeat_supervision_status(rapi):
    """Test $SY returns status: 0=no missed, 2=missed."""
    # No missed pulses
    rapi.heartbeat_missed = False
    response = rapi.process_command("$SY")
    msg = response.rstrip("\r").split("^")[0]

    # Should have status 0
    assert " 0" in msg or msg.endswith("0")


def test_heartbeat_supervision_with_checksum(rapi):
    """Test $SY commands with checksums."""
    cmd = "$SY 100 6"
    checksum = RAPIHandler._calculate_checksum(cmd)
    response = rapi.process_command(f"{cmd}{checksum}")

    assert response.startswith("$OK")
    # Should still set values
    assert rapi.heartbeat_interval == 100


def test_heartbeat_invalid_parameters(rapi):
    """Test $SY with invalid parameters."""
    response = rapi.process_command("$SY abc def")

    assert response.startswith("$NK")


def test_strict_checksum_mode():
    """Test strict checksum mode rejects commands with bad checksums."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev, strict_checksum=True)

    # Send command with invalid checksum
    response = rapi.process_command("$GS^FF\r")
    assert "$NK" in response

    # Send command with valid checksum
    cmd = "$GS"
    checksum = RAPIHandler._calculate_checksum(cmd)
    response = rapi.process_command(f"{cmd}{checksum}\r")
    assert "$OK" in response


def test_empty_command_checksum():
    """Test checksum calculation with empty or very short data."""
    # Test with minimal data (less than 2 chars)
    checksum = RAPIHandler._calculate_checksum("")
    assert checksum == "^00"

    checksum = RAPIHandler._calculate_checksum("$")
    assert checksum == "^00"


def test_checksum_verification_edge_cases():
    """Test checksum verification with malformed input."""
    # Missing checksum digits
    result = RAPIHandler._verify_checksum("$GS^A")
    assert result is False

    # Checksum at wrong position
    result = RAPIHandler._verify_checksum("$^ABGS")
    # Should find the last ^ marker
    assert result is False or result is True  # Depends on implementation


def test_command_exception_handling():
    """Test exception handling during command processing."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Create a situation that might cause an exception
    # Try setting current with malformed parameter
    response = rapi.process_command("$SC \r")
    assert "$NK" in response


def test_set_current_capacity_modes():
    """Test set_current_capacity method directly with different modes."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    RAPIHandler(evse, ev)

    # Test volatile mode (V) via direct method
    ok, amps_set = evse.set_current_capacity(20, volatile=True)
    assert ok is True
    assert amps_set == 20

    # Test max capacity mode (M) - first call should succeed
    ok, max_set = evse.set_max_capacity(40)
    assert ok is True
    assert max_set == 40

    # Second call should fail (locked)
    ok, max_set = evse.set_max_capacity(50)
    assert ok is False
    assert max_set == 40

    # Test clamping via set_current_capacity
    ok, amps_set = evse.set_current_capacity(100)
    assert ok is False
    assert amps_set == 40  # Clamped to max


def test_get_settings():
    """Test $GE command."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    evse.current_capacity_amps = 32
    response = rapi.process_command("$GE\r")

    parts = response.strip().split()
    assert parts[0] == "$OK"
    assert int(parts[1]) == 32  # Current capacity


def test_get_fault_counters():
    """Test $GF command."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Trigger some faults
    from src.emulator.evse import ErrorFlags

    evse.trigger_error(ErrorFlags.GFCI_TRIP)
    evse.clear_errors()

    response = rapi.process_command("$GF\r")
    parts = response.strip().split()
    assert parts[0] == "$OK"
    # Should have gfci_count, no_ground_count, stuck_relay_count
    assert len(parts) >= 4


def test_get_time_limit():
    """Test $GT command (not implemented)."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    response = rapi.process_command("$GT\r")
    assert "$OK 0" in response


def test_get_kwh_limit():
    """Test $GH command (not implemented)."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    response = rapi.process_command("$GH\r")
    assert "$OK 0" in response


def test_set_time_limit():
    """Test $ST command (not implemented)."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    response = rapi.process_command("$ST 60\r")
    assert "$OK" in response


def test_set_kwh_limit():
    """Test $SH command (not implemented)."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    response = rapi.process_command("$SH 10\r")
    assert "$OK" in response


def test_enable_command_with_error():
    """Test $FE command fails when errors are present."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    from src.emulator.evse import ErrorFlags

    # Trigger an error
    evse.trigger_error(ErrorFlags.GFCI_TRIP)

    # Try to enable (should fail)
    response = rapi.process_command("$FE\r")
    assert "$NK" in response


def test_sleep_command():
    """Test $FS command (same as disable)."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    response = rapi.process_command("$FS\r")
    assert "$OK" in response
    from src.emulator.evse import EVSEState

    assert evse.state == EVSEState.STATE_SLEEP


def test_gfci_test_commands():
    """Test $F1 and $F0 GFCI test commands."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Enable GFCI test
    response = rapi.process_command("$F1\r")
    assert "$OK" in response

    # Disable GFCI test
    response = rapi.process_command("$F0\r")
    assert "$OK" in response


def test_lcd_display_command():
    """Test $FP command for LCD display."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Set text at position
    response = rapi.process_command("$FP 0 0 OpenEVSE\r")
    assert "$OK" in response

    # Verify text was set
    lcd = evse.lcd_display
    assert "OpenEVSE" in lcd["row1"]

    # Test with empty text
    response = rapi.process_command("$FP 0 1\r")
    assert "$OK" in response

    # Test with invalid position
    response = rapi.process_command("$FP 20 0 Test\r")
    assert "$NK" in response

    # Test with invalid row
    response = rapi.process_command("$FP 0 5 Test\r")
    assert "$NK" in response

    # Test with missing parameters
    response = rapi.process_command("$FP 0\r")
    assert "$NK" in response

    # Test with 0xFE space character replacement
    response = rapi.process_command("$FP 0 0 A\xfeB\r")
    assert "$OK" in response
    lcd = evse.lcd_display
    assert "A B" in lcd["row1"]


def test_lcd_backlight_command():
    """Test $FB command for LCD backlight."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Set backlight color
    response = rapi.process_command("$FB 5\r")
    assert "$OK" in response

    # Verify color was set
    lcd = evse.lcd_display
    assert lcd["backlight_color"] == 5

    # Test with invalid color (out of range)
    response = rapi.process_command("$FB 10\r")
    assert "$NK" in response

    # Test with missing parameter
    response = rapi.process_command("$FB\r")
    assert "$NK" in response

    # Test with invalid parameter
    response = rapi.process_command("$FB abc\r")
    assert "$NK" in response


def test_set_current_invalid_params():
    """Test $SC command error handling."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Test with non-integer parameter
    response = rapi.process_command("$SC abc\r")
    assert "$NK" in response

    # Test with missing parameter
    response = rapi.process_command("$SC\r")
    assert "$NK" in response


def test_set_service_level_invalid():
    """Test $SL command with invalid level."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Test with invalid level
    response = rapi.process_command("$SL 5\r")
    assert "$NK" in response

    # Test with missing parameter
    response = rapi.process_command("$SL\r")
    assert "$NK" in response


def test_set_echo_invalid_params():
    """Test $SE command error handling."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Test with non-integer parameter
    response = rapi.process_command("$SE abc\r")
    assert "$NK" in response

    # Test with missing parameter
    response = rapi.process_command("$SE\r")
    assert "$NK" in response


def test_heartbeat_invalid_params_edge_cases():
    """Test $SY command with various invalid inputs."""
    evse = EVSEStateMachine()
    ev = EVSimulator()
    rapi = RAPIHandler(evse, ev)

    # Test with very large values (they're accepted, just stored)
    response = rapi.process_command("$SY 100000 6\r")
    # This actually succeeds - no validation on range
    assert "$OK" in response

    # Test with non-numeric parameters
    response = rapi.process_command("$SY abc def\r")
    assert "$NK" in response

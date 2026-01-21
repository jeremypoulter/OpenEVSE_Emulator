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

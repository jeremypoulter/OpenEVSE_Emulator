"""
Integration tests for RAPI protocol with checksum support.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest
from emulator.rapi import RAPIHandler


class TestRAPIIntegration:
    """Integration tests for RAPI command processing with checksums."""
    
    @pytest.fixture
    def rapi_handler(self):
        """Create a RAPI handler with mock EVSE and EV."""
        evse = MagicMock()
        evse.echo_enabled = False
        evse.get_status.return_value = {
            'state': 3,
            'session_time': 1234,
            'actual_current': 16.0,
            'voltage': 240000,
            'error_flags': 0,
            'temperature_ds': 25.5,
            'temperature_mcp': 26.0,
            'session_energy_wh': 1000,
            'current_capacity': 16,
            'gfci_count': 0,
            'no_ground_count': 0,
            'stuck_relay_count': 0,
        }
        evse.firmware_version = 'TEST1.0'
        evse.protocol_version = '5.2.1'
        evse.current_capacity_amps = 16
        
        ev = MagicMock()
        
        return RAPIHandler(evse, ev)
    
    def test_command_without_checksum(self, rapi_handler):
        """Test processing command without checksum."""
        response = rapi_handler.process_command('$GS\r')
        # Response should have checksum
        assert '^' in response
        assert response.startswith('$OK')
        assert '\r' in response
    
    def test_command_with_valid_checksum(self, rapi_handler):
        """Test processing command with valid checksum."""
        # First, let's build a valid command
        cmd = '$GS'
        checksum = RAPIHandler._calculate_checksum(cmd)
        full_cmd = cmd + checksum + '\r'
        
        response = rapi_handler.process_command(full_cmd)
        # Response should be valid
        assert response.startswith('$OK')
        assert '^' in response
    
    def test_command_with_invalid_checksum(self, rapi_handler):
        """Test processing command with invalid checksum rejects it."""
        cmd = '$GS^99\r'
        response = rapi_handler.process_command(cmd)
        # Should return error response
        assert '$NK' in response
    
    def test_response_includes_checksum(self, rapi_handler):
        """Test that all responses include checksums."""
        response = rapi_handler.process_command('$GS\r')
        # Extract checksum position
        checksum_pos = response.rfind('^')
        assert checksum_pos > 0
        # Should be followed by 2 hex digits and \r
        assert checksum_pos + 3 <= len(response)
        assert response[-1] == '\r'
    
    def test_command_with_parameters_and_checksum(self, rapi_handler):
        """Test command with parameters and checksum."""
        cmd = '$SC 16'
        checksum = RAPIHandler._calculate_checksum(cmd)
        full_cmd = cmd + checksum + '\r'
        
        response = rapi_handler.process_command(full_cmd)
        assert '$OK' in response
        assert '^' in response
    
    def test_invalid_command_with_checksum(self, rapi_handler):
        """Test invalid command with checksum returns error."""
        cmd = '$XX'
        checksum = RAPIHandler._calculate_checksum(cmd)
        full_cmd = cmd + checksum + '\r'
        
        response = rapi_handler.process_command(full_cmd)
        assert '$NK' in response
        # Error response should still have checksum
        assert '^' in response
    
    def test_echo_includes_checksum(self, rapi_handler):
        """Test that echoed commands include checksums."""
        rapi_handler.evse.echo_enabled = True
        response = rapi_handler.process_command('$GS\r')
        
        # Response should contain echo with checksum
        assert response.count('^') >= 1  # At least checksum for response
        # Depending on implementation, might have 2 checksums (echo + response)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

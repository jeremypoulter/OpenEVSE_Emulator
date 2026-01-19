"""
Tests for RAPI checksum functionality.
"""

import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest
from emulator.rapi import RAPIHandler


class TestRAPIChecksum:
    """Test RAPI checksum calculation and verification."""
    
    def test_checksum_calculation_simple(self):
        """Test checksum calculation for simple string."""
        # '$OK' should have checksum
        result = RAPIHandler._calculate_checksum('$OK')
        assert result.startswith('^')
        assert len(result) == 3  # ^ + 2 hex digits
    
    def test_checksum_calculation_with_data(self):
        """Test checksum calculation for response with data."""
        result = RAPIHandler._calculate_checksum('$OK 3 1234')
        assert result.startswith('^')
        assert len(result) == 3
    
    def test_checksum_xor_logic(self):
        """Test that checksum uses XOR operation."""
        # XOR of '$' (0x24) = 0x24
        result = RAPIHandler._calculate_checksum('$')
        assert result == '^24'
        
        # XOR of 'OK' (0x4F ^ 0x4B) = 0x04
        result = RAPIHandler._calculate_checksum('OK')
        assert result == '^04'
    
    def test_append_checksum(self):
        """Test appending checksum to response."""
        result = RAPIHandler._append_checksum('$OK')
        # Should be '$OK' + checksum
        assert result.startswith('$OK')
        assert '^' in result
        assert len(result) == 6  # $OK + ^ + 2 hex
    
    def test_verify_checksum_valid(self):
        """Test verification of valid checksum."""
        # Calculate checksum first
        data = '$OK'
        checksummed = RAPIHandler._append_checksum(data)
        # Should verify successfully
        assert RAPIHandler._verify_checksum(checksummed) is True
    
    def test_verify_checksum_invalid(self):
        """Test verification of invalid checksum."""
        # Create response with wrong checksum
        data = '$OK^99'
        assert RAPIHandler._verify_checksum(data) is False
    
    def test_verify_checksum_missing(self):
        """Test that missing checksum is considered valid."""
        # Response without checksum should be valid (backwards compatibility)
        data = '$OK'
        assert RAPIHandler._verify_checksum(data) is True
    
    def test_checksum_with_spaces(self):
        """Test checksum calculation with spaces in data."""
        result1 = RAPIHandler._append_checksum('$OK 3 1234')
        result2 = RAPIHandler._append_checksum('$OK 3 1235')
        # Different data should produce different checksums
        assert result1 != result2
    
    def test_checksum_reproducible(self):
        """Test that checksums are reproducible."""
        data = '$OK 16'
        result1 = RAPIHandler._append_checksum(data)
        result2 = RAPIHandler._append_checksum(data)
        assert result1 == result2
    
    def test_checksum_case_sensitive(self):
        """Test that checksums are case-sensitive."""
        lower = RAPIHandler._append_checksum('$ok')
        upper = RAPIHandler._append_checksum('$OK')
        # Different cases should produce different checksums
        assert lower != upper


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

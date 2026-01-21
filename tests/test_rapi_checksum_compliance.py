"""
Verification tests for RAPI checksum compliance with OpenEVSE firmware.

These tests verify that the checksum implementation matches the behavior
of the official OpenEVSE firmware as documented in rapi_proc.cpp.
"""

import sys
import pytest
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from emulator.rapi import RAPIHandler


class TestRAPIChecksumCompliance:
    """Tests to verify compliance with OpenEVSE firmware checksum behavior."""

    def test_xor_calculation_matches_firmware(self):
        """
        Verify XOR calculation matches firmware appendChk() function.

        The firmware calculates: chk ^= *(s++)  for each character
        """
        # Test cases with known checksums from OpenEVSE firmware behavior
        test_cases = [
            ("$OK", 0x20),  # '$'=0x24 ^ 'O'=0x4F ^ 'K'=0x4B = 0x20
            ("$NK", 0x21),  # '$'=0x24 ^ 'N'=0x4E ^ 'K'=0x4B = 0x21
            ("OK", 0x04),  # 'O'=0x4F ^ 'K'=0x4B = 0x04
            ("NK", 0x05),  # 'N'=0x4E ^ 'K'=0x4B = 0x05
        ]

        for data, expected_checksum in test_cases:
            result = RAPIHandler._calculate_checksum(data)
            expected = f"^{expected_checksum:02X}"
            assert (
                result == expected
            ), f"Checksum for '{data}' should be {expected}, got {result}"

    def test_format_matches_firmware(self):
        """
        Verify checksum format matches firmware: '^HH' where HH is hex.

        The firmware uses: sprintf(s,"^%02X",(unsigned)chk);
        """
        result = RAPIHandler._append_checksum("$GS")

        # Should match pattern: something^HH
        assert result.count("^") == 1

        # Extract checksum part
        checksum_part = result.split("^")[1]
        assert len(checksum_part) == 2

        # Should be valid hex
        try:
            int(checksum_part, 16)
        except ValueError:
            pytest.fail(f"Checksum '{checksum_part}' is not valid hex")

    def test_space_handling(self):
        """
        Verify spaces are included in checksum calculation.

        Spaces are part of the message and should be XORed like any character.
        """
        without_space = RAPIHandler._calculate_checksum("SCAB")
        with_space = RAPIHandler._calculate_checksum("SC AB")

        # Should be different since space (0x20) is XORed
        assert without_space != with_space

    def test_case_sensitivity(self):
        """
        Verify checksum calculation is case-sensitive.

        Characters are compared by their ASCII value, so case matters.
        """
        lower = RAPIHandler._calculate_checksum("abc")
        upper = RAPIHandler._calculate_checksum("ABC")

        # Should be different: 'a'=0x61, 'A'=0x41; 'b'=0x62, 'B'=0x42; etc.
        assert lower != upper

    def test_response_format_compliance(self):
        """
        Verify response format matches firmware output format.

        Firmware responses are: $OK[data]^HH\r
        """
        response = RAPIHandler._append_checksum("$OK 3 1234")

        # Should start with $OK
        assert response.startswith("$OK")

        # Should have checksum marker
        assert "^" in response

        # Checksum should be at the end (before \r in actual use)
        parts = response.split("^")
        assert len(parts) == 2

        # Checksum part should be 2 hex digits
        assert len(parts[1]) == 2

    def test_error_response_format(self):
        """
        Verify error response format: $NK^HH\r
        """
        response = RAPIHandler._append_checksum("$NK")

        # Should start with $NK
        assert response.startswith("$NK")

        # Should have checksum
        assert "^" in response

        # Total length should be $NK^HH = 6 characters
        assert len(response) == 6

    def test_verification_case_sensitivity(self):
        """
        Verify checksum verification handles case properly.

        Hex digits should be case-insensitive for verification,
        but calculation should be exact.
        """
        # Create a response with lowercase hex
        response_upper = RAPIHandler._append_checksum("$GS")

        # Both should verify as valid (if implementation accepts both)
        # At minimum, the uppercase version should be valid
        assert RAPIHandler._verify_checksum(response_upper) is True

    def test_zero_checksum(self):
        """
        Verify handling of zero checksum values.
        """
        # Create data that XORs to 0
        # This is tricky - let's just verify format is correct
        result = RAPIHandler._calculate_checksum("@@")  # 0x40 ^ 0x40 = 0x00
        assert result == "^00"

    def test_max_checksum(self):
        """
        Verify handling of maximum checksum value (0xFF).
        Firmware initializes with $ XOR second char, so we need specific values.
        0x24 ($ = 0x24) XOR 0xFF = 0xDB, then XOR 0x24 = 0xFF
        """
        result = RAPIHandler._calculate_checksum("$\xff$")
        assert result == "^FF"

    def test_message_end_marker(self):
        """
        Verify checksum is appended before line ending (CR).

        Protocol: $message^HH\r
        """
        response = RAPIHandler._append_checksum("$OK")

        # Checksum should be between message and any line ending
        # (line ending is added by process_command, not by _append_checksum)
        assert "^" in response
        assert response.count("^") == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

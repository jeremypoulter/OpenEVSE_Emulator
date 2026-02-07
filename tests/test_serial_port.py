"""Tests for VirtualSerialPort initialization and validation."""

import pytest
from src.emulator.serial_port import VirtualSerialPort


class TestVirtualSerialPortValidation:
    """Test input validation for VirtualSerialPort."""

    def test_valid_defaults(self):
        """Test that default values are valid."""
        port = VirtualSerialPort()
        assert port.reconnect_timeout_sec == 60
        assert port.reconnect_backoff_ms == 1000

    def test_valid_zero_timeout(self):
        """Test that timeout can be 0 (infinite retry)."""
        port = VirtualSerialPort(reconnect_timeout_sec=0)
        assert port.reconnect_timeout_sec == 0

    def test_valid_zero_backoff(self):
        """Test that backoff can be 0."""
        port = VirtualSerialPort(reconnect_backoff_ms=0)
        assert port.reconnect_backoff_ms == 0

    def test_valid_custom_values(self):
        """Test that custom positive values work."""
        port = VirtualSerialPort(reconnect_timeout_sec=30, reconnect_backoff_ms=500)
        assert port.reconnect_timeout_sec == 30
        assert port.reconnect_backoff_ms == 500

    def test_negative_timeout_raises_error(self):
        """Test that negative timeout raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            VirtualSerialPort(reconnect_timeout_sec=-1)
        assert "reconnect_timeout_sec must be >= 0" in str(exc_info.value)
        assert "-1" in str(exc_info.value)

    def test_negative_backoff_raises_error(self):
        """Test that negative backoff raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            VirtualSerialPort(reconnect_backoff_ms=-1)
        assert "reconnect_backoff_ms must be >= 0" in str(exc_info.value)
        assert "-1" in str(exc_info.value)

    def test_both_negative_raises_timeout_error_first(self):
        """Test that when both are negative, timeout error is raised first."""
        with pytest.raises(ValueError) as exc_info:
            VirtualSerialPort(reconnect_timeout_sec=-10, reconnect_backoff_ms=-5)
        # Timeout validation happens first
        assert "reconnect_timeout_sec must be >= 0" in str(exc_info.value)

    def test_pty_mode_with_valid_params(self):
        """Test PTY mode initialization with validation."""
        port = VirtualSerialPort(
            mode="pty",
            pty_path="/tmp/test_pty",
            reconnect_timeout_sec=45,
            reconnect_backoff_ms=750,
        )
        assert port.mode == "pty"
        assert port.pty_path == "/tmp/test_pty"
        assert port.reconnect_timeout_sec == 45
        assert port.reconnect_backoff_ms == 750

    def test_tcp_mode_with_valid_params(self):
        """Test TCP mode initialization with validation."""
        port = VirtualSerialPort(
            mode="tcp",
            tcp_port=9000,
            reconnect_timeout_sec=20,
            reconnect_backoff_ms=200,
        )
        assert port.mode == "tcp"
        assert port.tcp_port == 9000
        assert port.reconnect_timeout_sec == 20
        assert port.reconnect_backoff_ms == 200

    def test_tcp_mode_with_negative_backoff_raises_error(self):
        """Test TCP mode with negative backoff raises error."""
        with pytest.raises(ValueError) as exc_info:
            VirtualSerialPort(mode="tcp", tcp_port=9000, reconnect_backoff_ms=-100)
        assert "reconnect_backoff_ms must be >= 0" in str(exc_info.value)

    def test_large_valid_values(self):
        """Test that large positive values are accepted."""
        port = VirtualSerialPort(reconnect_timeout_sec=3600, reconnect_backoff_ms=60000)
        assert port.reconnect_timeout_sec == 3600
        assert port.reconnect_backoff_ms == 60000

"""Tests for VirtualSerialPort initialization and validation."""

from unittest.mock import MagicMock, patch

import pytest
import serial

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

    def test_device_mode_with_valid_params(self):
        """Test device mode initialization with validation."""
        port = VirtualSerialPort(
            mode="device",
            device_path="/dev/ttyUSB0",
            baudrate=57600,
            reconnect_timeout_sec=45,
            reconnect_backoff_ms=750,
        )
        assert port.mode == "device"
        assert port.device_path == "/dev/ttyUSB0"
        assert port.baudrate == 57600
        assert port.reconnect_timeout_sec == 45
        assert port.reconnect_backoff_ms == 750

    def test_large_valid_values(self):
        """Test that large positive values are accepted."""
        port = VirtualSerialPort(reconnect_timeout_sec=3600, reconnect_backoff_ms=60000)
        assert port.reconnect_timeout_sec == 3600
        assert port.reconnect_backoff_ms == 60000


class TestSplitCommands:
    """Test the shared command-buffer splitting helper."""

    def test_splits_cr_terminated_command(self):
        commands, remainder = VirtualSerialPort._split_commands("$GS\r")
        assert commands == ["$GS\r"]
        assert remainder == ""

    def test_keeps_partial_command_in_remainder(self):
        commands, remainder = VirtualSerialPort._split_commands("$GS\r$GC")
        assert commands == ["$GS\r"]
        assert remainder == "$GC"

    def test_no_terminator_returns_no_commands(self):
        commands, remainder = VirtualSerialPort._split_commands("$GS")
        assert commands == []
        assert remainder == "$GS"


class TestDeviceMode:
    """Test real hardware serial device mode."""

    def test_start_device_without_path_fails(self):
        """Starting device mode without a configured path should fail cleanly."""
        port = VirtualSerialPort(mode="device")
        assert port.start(lambda cmd: None) is False

    def test_open_device_success(self):
        """Opening the device should succeed and store the connection."""
        port = VirtualSerialPort(mode="device", device_path="/dev/ttyUSB0")
        with patch("src.emulator.serial_port.serial.Serial") as mock_serial:
            mock_serial.return_value = MagicMock()
            assert port._open_device() is True
            mock_serial.assert_called_once_with(
                port="/dev/ttyUSB0", baudrate=115200, timeout=0.1
            )
            assert port.serial_conn is not None

    def test_open_device_failure(self):
        """A SerialException while opening should be handled, not raised."""
        port = VirtualSerialPort(mode="device", device_path="/dev/ttyUSB0")
        with patch("src.emulator.serial_port.serial.Serial") as mock_serial:
            mock_serial.side_effect = serial.SerialException("no such device")
            assert port._open_device() is False
            assert port.serial_conn is None

    def test_device_read_loop_processes_command_and_writes_response(self):
        """A complete command read from the device should invoke the callback
        and write its response back."""
        port = VirtualSerialPort(mode="device", device_path="/dev/ttyUSB0")
        port.running = True
        port.serial_conn = MagicMock()

        # First read returns a full command, second read stops the loop.
        call_count = 0

        def read_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"$GS\r"
            port.running = False
            return b""

        port.serial_conn.read.side_effect = read_side_effect
        port.data_callback = MagicMock(return_value="$OK\r")

        port._device_read_loop()

        port.data_callback.assert_called_once_with("$GS\r")
        port.serial_conn.write.assert_called_once_with(b"$OK\r")

    def test_device_read_loop_timeout_does_not_stop_loop(self):
        """An empty read (pyserial timeout) must not be treated as disconnect."""
        port = VirtualSerialPort(mode="device", device_path="/dev/ttyUSB0")
        port.running = True
        port.serial_conn = MagicMock()

        call_count = 0

        def read_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                port.running = False
            return b""

        port.serial_conn.read.side_effect = read_side_effect

        port._device_read_loop()

        assert call_count >= 3

    def test_device_read_loop_stops_on_serial_exception(self):
        """A SerialException (e.g. device unplugged) must end the read loop."""
        port = VirtualSerialPort(mode="device", device_path="/dev/ttyUSB0")
        port.running = True
        port.serial_conn = MagicMock()
        port.serial_conn.read.side_effect = serial.SerialException(
            "device disconnected"
        )

        # Should return promptly rather than raising or hanging.
        port._device_read_loop()

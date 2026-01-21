"""
Tests for RAPI async notification messages.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.emulator.rapi import RAPIHandler
from src.emulator.evse import EVSEStateMachine
from src.emulator.ev import EVSimulator


class TestRAPIAsyncNotifications:
    """Test async RAPI notifications."""

    def setup_method(self):
        """Set up test fixtures."""
        self.evse = EVSEStateMachine()
        self.ev = EVSimulator()
        self.rapi = RAPIHandler(self.evse, self.ev)
        self.async_messages = []

        # Set up callback to capture async messages
        def capture_message(msg):
            self.async_messages.append(msg)

        self.rapi.set_async_callback(capture_message)

    def test_boot_notification_format(self):
        """Test $AB boot notification format."""
        self.rapi.send_boot_notification()

        assert len(self.async_messages) == 1
        msg = self.async_messages[0]

        # Should be $AB 00 <firmware>^<checksum>\r
        assert msg.startswith("$AB 00 ")
        assert "^" in msg
        assert msg.endswith("\r")

        # Extract parts
        parts = msg.strip().split(" ")
        assert parts[0] == "$AB"
        assert parts[1] == "00"  # Boot OK

    def test_boot_notification_checksum(self):
        """Test boot notification has valid checksum."""
        self.rapi.send_boot_notification()

        msg = self.async_messages[0]
        # Verify checksum is present
        assert "^" in msg

        # Extract message without line ending
        msg_without_ending = msg.rstrip("\r")
        checksum_start = msg_without_ending.rfind("^")
        assert checksum_start > 0

        # Checksum should be 2 hex digits
        checksum_str = msg_without_ending[checksum_start + 1 :]
        assert len(checksum_str) == 2
        assert all(c in "0123456789ABCDEF" for c in checksum_str)

    def test_state_transition_format(self):
        """Test $AT state transition format."""
        self.rapi.send_state_transition()

        assert len(self.async_messages) == 1
        msg = self.async_messages[0]

        # Should be $AT <state> <pilot> <current> <vflags>^<checksum>\r
        assert msg.startswith("$AT ")
        assert "^" in msg
        assert msg.endswith("\r")

        # Extract parts (before checksum)
        msg_without_ending = msg.rstrip("\r")
        parts = msg_without_ending.split("^")[0].split(" ")

        assert parts[0] == "$AT"
        assert len(parts) == 5  # $AT + 4 parameters

    def test_state_transition_values(self):
        """Test state transition contains correct values."""
        # Set a known state
        self.evse.current_capacity_amps = 32

        self.rapi.send_state_transition()

        msg = self.async_messages[0]
        msg_without_ending = msg.rstrip("\r")
        parts = msg_without_ending.split("^")[0].split(" ")

        # parts: $AT evsestate pilotstate currentcapacity vflags
        assert parts[0] == "$AT"

        # Check state is hex format
        evse_state = parts[1]
        assert len(evse_state) == 2
        assert all(c in "0123456789ABCDEF" for c in evse_state)

        # Check current capacity
        current = int(parts[3])
        assert current == 32

        # Check vflags (error flags) is hex
        vflags = parts[4]
        assert len(vflags) == 4  # vflags is 4 hex chars (16-bit value)
        assert all(c in "0123456789ABCDEF" for c in vflags)

    def test_state_change_callback_triggers_notification(self):
        """Test that state changes trigger async notifications."""
        # Wire up state change callback
        notification_count = [0]  # Use list to allow modification in closure

        def on_state_change(state):
            notification_count[0] += 1
            self.rapi.send_state_transition()

        self.evse.set_state_change_callback(on_state_change)

        # Clear any previous messages
        self.async_messages.clear()

        # EVSE starts in STATE_A, trigger a state change to STATE_B
        self.evse.update_state("B")  # Connected

        # Should have sent a notification
        assert notification_count[0] == 1
        assert len(self.async_messages) == 1
        msg = self.async_messages[0]
        assert msg.startswith("$AT ")

    def test_multiple_state_changes(self):
        """Test multiple state changes send multiple notifications."""
        # Wire up state change callback
        notification_count = [0]

        def on_state_change(state):
            notification_count[0] += 1
            self.rapi.send_state_transition()

        self.evse.set_state_change_callback(on_state_change)

        self.async_messages.clear()

        # Trigger state changes: A->B->C->A
        self.evse.update_state("B")  # Connected
        self.evse.update_state("C")  # Charging
        self.evse.update_state("A")  # Disconnected

        # Should have sent 3 notifications
        assert notification_count[0] == 3
        assert len(self.async_messages) == 3
        assert all(msg.startswith("$AT ") for msg in self.async_messages)

    def test_boot_notification_contains_firmware_version(self):
        """Test boot notification includes firmware version."""
        fw_version = "8.2.1"
        self.evse.firmware_version = fw_version

        self.rapi.send_boot_notification()

        msg = self.async_messages[0]
        assert fw_version in msg

#!/usr/bin/env python3
"""
OpenEVSE Emulator - Main Entry Point

Integrates all components and manages the simulation loop.
"""

import argparse
import json
import signal
import sys
import threading
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from emulator.evse import EVSEStateMachine  # noqa: E402
from emulator.ev import EVSimulator  # noqa: E402
from emulator.rapi import RAPIHandler  # noqa: E402
from emulator.serial_port import VirtualSerialPort  # noqa: E402
from web.api import WebAPI  # noqa: E402


def default_config() -> dict:
    """Return default configuration."""
    return {
        "serial": {"mode": "pty", "tcp_port": 8023, "baudrate": 115200},
        "evse": {
            "firmware_version": "8.2.1",
            "protocol_version": "5.0.1",
            "default_current": 32,
            "service_level": "L2",
            "gfci_self_test": True,
        },
        "ev": {"battery_capacity_kwh": 75, "max_charge_rate_kw": 7.2},
        "web": {"host": "0.0.0.0", "port": 8080},
        "simulation": {
            "update_interval_ms": 1000,
            "temperature_simulation": True,
            "realistic_charge_curve": True,
        },
    }


def load_config(config_path: str) -> dict:
    """Load configuration from JSON file."""
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Config file {config_path} not found, using defaults")
        return default_config()
    except json.JSONDecodeError as e:
        print(f"Error parsing config file: {e}")
        sys.exit(1)


def set_nested(config: dict, dot_path: str, value) -> None:
    """Set a nested dict key from a dot path, e.g. set_nested(c, 'serial.tcp_port', 8024)."""
    parts = dot_path.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


# Mapping from argparse dest (option name with underscores) to config dot path.
_CLI_OVERRIDE_PATHS = {
    "serial_mode": "serial.mode",
    "serial_tcp_port": "serial.tcp_port",
    "serial_baudrate": "serial.baudrate",
    "evse_firmware_version": "evse.firmware_version",
    "evse_protocol_version": "evse.protocol_version",
    "evse_default_current": "evse.default_current",
    "evse_service_level": "evse.service_level",
    "evse_gfci_self_test": "evse.gfci_self_test",
    "ev_battery_capacity_kwh": "ev.battery_capacity_kwh",
    "ev_max_charge_rate_kw": "ev.max_charge_rate_kw",
    "web_host": "web.host",
    "web_port": "web.port",
    "simulation_update_interval_ms": "simulation.update_interval_ms",
    "simulation_temperature_simulation": "simulation.temperature_simulation",
    "simulation_realistic_charge_curve": "simulation.realistic_charge_curve",
}


def _parse_args():
    """Parse command-line arguments. Options not passed have default=SUPPRESS."""
    p = argparse.ArgumentParser(
        description="OpenEVSE Emulator - override config via command line"
    )
    p.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON file (default: config.json)",
    )
    p.add_argument(
        "--serial-mode",
        dest="serial_mode",
        type=str,
        default=argparse.SUPPRESS,
        help="Virtual serial mode: pty or socket",
    )
    p.add_argument(
        "--serial-tcp-port",
        dest="serial_tcp_port",
        type=int,
        default=argparse.SUPPRESS,
        help="TCP port for socket serial mode (default: 8023)",
    )
    p.add_argument(
        "--serial-baudrate",
        dest="serial_baudrate",
        type=int,
        default=argparse.SUPPRESS,
        help="Serial baud rate (default: 115200)",
    )
    p.add_argument(
        "--evse-firmware-version",
        dest="evse_firmware_version",
        type=str,
        default=argparse.SUPPRESS,
        help="EVSE firmware version string reported to RAPI clients",
    )
    p.add_argument(
        "--evse-protocol-version",
        dest="evse_protocol_version",
        type=str,
        default=argparse.SUPPRESS,
        help="EVSE RAPI protocol version string",
    )
    p.add_argument(
        "--evse-default-current",
        dest="evse_default_current",
        type=int,
        default=argparse.SUPPRESS,
        help="Default EVSE current capacity in amps (e.g. 32)",
    )
    p.add_argument(
        "--evse-service-level",
        dest="evse_service_level",
        type=str,
        default=argparse.SUPPRESS,
        help="EVSE service level: L1 or L2",
    )
    p.add_argument(
        "--evse-gfci-self-test",
        dest="evse_gfci_self_test",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Enable GFCI self-test at boot",
    )
    p.add_argument(
        "--ev-battery-capacity-kwh",
        dest="ev_battery_capacity_kwh",
        type=float,
        default=argparse.SUPPRESS,
        help="Simulated EV battery capacity in kWh",
    )
    p.add_argument(
        "--ev-max-charge-rate-kw",
        dest="ev_max_charge_rate_kw",
        type=float,
        default=argparse.SUPPRESS,
        help="Simulated EV max charge rate in kW",
    )
    p.add_argument(
        "--web-host",
        dest="web_host",
        type=str,
        default=argparse.SUPPRESS,
        help="Web UI bind address (e.g. 0.0.0.0 or 127.0.0.1)",
    )
    p.add_argument(
        "--web-port",
        dest="web_port",
        type=int,
        default=argparse.SUPPRESS,
        help="Web UI HTTP port (default: 8080)",
    )
    p.add_argument(
        "--simulation-update-interval-ms",
        dest="simulation_update_interval_ms",
        type=int,
        default=argparse.SUPPRESS,
        help="Simulation loop update interval in milliseconds",
    )
    p.add_argument(
        "--simulation-temperature-simulation",
        dest="simulation_temperature_simulation",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Simulate EVSE temperature changes during charging",
    )
    p.add_argument(
        "--simulation-realistic-charge-curve",
        dest="simulation_realistic_charge_curve",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Use a realistic EV charge curve (taper near full SOC)",
    )
    return p.parse_args()


def apply_overrides(config: dict, args: argparse.Namespace) -> None:
    """Apply CLI overrides to config (only for options that were explicitly set)."""
    for dest, dot_path in _CLI_OVERRIDE_PATHS.items():
        if hasattr(args, dest):
            value = getattr(args, dest)
            set_nested(config, dot_path, value)


class OpenEVSEEmulator:
    """Main emulator orchestrator."""

    def __init__(
        self,
        config_path: str = "config.json",
        config: dict | None = None,
    ):
        """
        Initialize the emulator.

        Args:
            config_path: Path to configuration file (used when config is None).
            config: Optional pre-loaded config dict; when provided, config_path is ignored.
        """
        if config is not None:
            self.config = config
        else:
            self.config = load_config(config_path)

        # Create components
        evse_config = self.config["evse"]
        self.evse = EVSEStateMachine(
            firmware_version=evse_config["firmware_version"],
            protocol_version=evse_config["protocol_version"],
        )
        self.evse.current_capacity_amps = evse_config["default_current"]
        self.evse.service_level = evse_config["service_level"]

        ev_config = self.config["ev"]
        self.ev = EVSimulator(
            battery_capacity_kwh=ev_config["battery_capacity_kwh"],
            max_charge_rate_kw=ev_config["max_charge_rate_kw"],
        )

        self.rapi = RAPIHandler(self.evse, self.ev)

        serial_config = self.config["serial"]
        self.serial_port = VirtualSerialPort(
            mode=serial_config["mode"], tcp_port=serial_config["tcp_port"]
        )

        # Wire up state change callback to send async notifications
        self.evse.set_state_change_callback(self._on_state_change)

        web_config = self.config["web"]
        self.web_api = WebAPI(
            self.evse, self.ev, host=web_config["host"], port=web_config["port"]
        )

        # Simulation state
        self.running = False
        self.simulation_thread = None
        self.last_update_time = time.time()

    def start(self):
        """Start the emulator."""
        print("=" * 60)
        print("OpenEVSE Emulator v1.0.0")
        print("=" * 60)

        # Start virtual serial port
        print("\nStarting virtual serial port...")
        if not self.serial_port.start(self._handle_serial_data):
            print("Failed to start serial port")
            return False

        print(f"Serial port: {self.serial_port.get_port_info()}")

        # Set up async message callback
        self.rapi.set_async_callback(self._send_async_message)

        # Send boot notification
        print("\nSending boot notification...")
        self.rapi.send_boot_notification()

        # Start simulation loop
        print("\nStarting simulation loop...")
        self.running = True
        self.simulation_thread = threading.Thread(
            target=self._simulation_loop, daemon=True
        )
        self.simulation_thread.start()

        # Start web server (blocking)
        print("\nStarting web server...")
        print(f"Web UI: http://localhost:{self.config['web']['port']}")
        print("\n" + "=" * 60)
        print("Emulator is running. Press Ctrl+C to stop.")
        print("=" * 60 + "\n")

        try:
            self.web_api.run()
        except KeyboardInterrupt:
            print("\nShutting down...")
            self.stop()

    def stop(self):
        """Stop the emulator."""
        self.running = False

        if self.simulation_thread:
            self.simulation_thread.join(timeout=2.0)

        self.serial_port.stop()
        print("Emulator stopped.")

    def _simulation_loop(self):
        """Main simulation loop."""
        update_interval = self.config["simulation"]["update_interval_ms"] / 1000.0

        while self.running:
            current_time = time.time()
            delta_time = current_time - self.last_update_time
            self.last_update_time = current_time

            # Update EV pilot state and get what EVSE should see
            ev_pilot_state = self.ev.get_pilot_resistance()

            # Update EVSE state based on EV
            self.evse.update_state(ev_pilot_state)

            # Get EVSE output
            evse_status = self.evse.get_status()
            offered_current = evse_status["current_capacity"]
            voltage = evse_status["voltage"] / 1000.0  # Convert to volts

            # Update EV charging based on EVSE offer
            self.ev.update_charging(offered_current, voltage, delta_time)

            # Update EVSE charging metrics
            ev_status = self.ev.get_status()
            self.evse.update_charging(ev_status["actual_charge_rate_kw"], delta_time)

            # Sleep until next update
            time.sleep(update_interval)

    def _handle_serial_data(self, data: str) -> str:
        """
        Handle data received on serial port.

        Args:
            data: Received data string

        Returns:
            Response string to send back
        """
        # Process RAPI command
        response = self.rapi.process_command(data)

        # Log to console
        print(f"RAPI: {data.strip()} -> {response.strip()}")

        return response

    def _send_async_message(self, message: str):
        """Send async message through serial port."""
        if self.serial_port:
            self.serial_port.write(message)

    def _on_state_change(self, new_state):
        """Handle EVSE state changes and send async notification."""
        self.rapi.send_state_transition()


def main():
    """Main entry point."""
    args = _parse_args()
    config = load_config(args.config)
    apply_overrides(config, args)

    emulator = OpenEVSEEmulator(config=config)

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\nReceived interrupt signal")
        emulator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start emulator
    emulator.start()


if __name__ == "__main__":
    main()

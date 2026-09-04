#!/usr/bin/env python3
"""
OpenEVSE Emulator - Main Entry Point

Integrates all components and manages the simulation loop.
"""

import signal
import sys
import threading
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from emulator.cli import parse_arguments  # noqa: E402
from emulator.config import (  # noqa: E402
    CLI_OVERRIDE_PATHS,
    apply_cli_overrides,
    apply_env_overrides,
    load_config,
)
from emulator.engine import EngineError, FirmwareEngine  # noqa: E402
from emulator.evse import EVSEStateMachine  # noqa: E402
from emulator.ev import EVSimulator  # noqa: E402
from emulator.rapi import RAPIHandler  # noqa: E402
from emulator.serial_port import VirtualSerialPort  # noqa: E402
from emulator.telemetry import build_reporter  # noqa: E402
from web.api import WebAPI  # noqa: E402


def apply_overrides(config: dict, args) -> None:
    """Apply CLI overrides to config (only for options that were explicitly set)."""
    args_dict = {k: v for k, v in vars(args).items() if k in CLI_OVERRIDE_PATHS}
    apply_cli_overrides(config, args_dict)


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
            range_km_at_full=ev_config.get("range_km_at_full", 400.0),
            charge_limit_soc=ev_config.get("charge_limit_soc", 100.0),
        )

        # Optional push of the simulated vehicle's battery state to a real
        # OpenEVSE. Misconfiguration here must not stop the emulator starting,
        # since the rest of it is still useful without telemetry.
        reporting_config = self.config.get("reporting", {})
        try:
            self.reporter = build_reporter(self.ev, reporting_config)
        except ValueError as e:
            print(f"Vehicle telemetry reporting disabled: {e}")
            print("Configure it at runtime with POST /api/reporting/config")
            reporting_config = {}
            self.reporter = build_reporter(self.ev, reporting_config)

        # Engine mode replaces the Python state machine and RAPI handler with
        # the real firmware. Everything else -- the EV model, the serial port,
        # the web UI -- carries on unchanged; self.evse becomes a mirror of
        # what the firmware reports rather than a simulation in its own right.
        engine_config = self.config.get("engine", {})
        self.engine = None
        if engine_config.get("enabled") or engine_config.get("binary"):
            self.engine = FirmwareEngine(
                binary=engine_config["binary"],
                board=engine_config.get("board") or None,
                eeprom=engine_config.get("eeprom") or None,
                wait_ms=engine_config.get("wait_ms", 10000),
            )
            self.rapi = self.engine
        else:
            self.rapi = RAPIHandler(self.evse, self.ev)

        serial_config = self.config["serial"]
        self.serial_port = VirtualSerialPort(
            mode=serial_config["mode"],
            tcp_port=serial_config["tcp_port"],
            pty_path=serial_config.get("pty_path"),
            baudrate=serial_config.get("baudrate", 115200),
            device_path=serial_config.get("device"),
            reconnect_timeout_sec=serial_config.get("reconnect_timeout_sec", 60),
            reconnect_backoff_ms=serial_config.get("reconnect_backoff_ms", 1000),
        )

        # Wire up state change callback to send async notifications
        self.evse.set_state_change_callback(self._on_state_change)

        web_config = self.config["web"]
        self.web_api = WebAPI(
            self.evse,
            self.ev,
            host=web_config["host"],
            port=web_config["port"],
            reporter=self.reporter,
            reporting_config=reporting_config,
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

        if self.engine:
            print("\nStarting firmware engine...")
            try:
                self.engine.start()
            except EngineError as e:
                print(f"Failed to start firmware engine: {e}")
                return False
            board = self.engine.board
            version = self.engine.hello.get("version", "unknown")
            print(f"Engine: {self.engine.binary}")
            print(f"        board={board} version={version}")

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

        # Start vehicle telemetry reporting (no-op when not configured)
        self.reporter.start()

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

        # The web API can replace the reporter at runtime, so stop whichever
        # one is current rather than the one built at startup.
        if self.web_api.reporter:
            self.web_api.reporter.stop()
        self.serial_port.stop()
        if self.engine:
            self.engine.stop()
        print("Emulator stopped.")

    def _simulation_loop(self):
        """Main simulation loop."""
        update_interval = self.config["simulation"]["update_interval_ms"] / 1000.0

        while self.running:
            current_time = time.time()
            delta_time = current_time - self.last_update_time
            self.last_update_time = current_time

            if self.engine:
                # The firmware decides. Present the vehicle to its inputs and
                # adopt whatever it reports; nothing here works out what the
                # state ought to be, which is the point of engine mode.
                self.engine.apply_ev(self.ev)
                self.engine.mirror_into(self.evse)
            else:
                # Update EV pilot state and get what EVSE should see
                ev_pilot_state = self.ev.get_pilot_resistance()

                # Update EVSE state based on EV
                self.evse.update_state(ev_pilot_state)

            # Get EVSE output
            evse_status = self.evse.get_status()
            offered_current = evse_status["current_capacity"]
            voltage = evse_status["voltage"] / 1000.0  # Convert to volts

            if self.engine and not self.engine.relay_closed():
                # No contactor, no current. Without this the vehicle would go
                # on drawing through an open relay whenever the firmware
                # faulted, and the fault would look harmless.
                offered_current = 0

            # Update EV charging based on EVSE offer
            self.ev.update_charging(offered_current, voltage, delta_time)

            # Update EVSE charging metrics. In engine mode the firmware meters
            # the current itself from the CT the engine feeds it, but the
            # emulator's own energy counters still back the web UI.
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
    args = parse_arguments()
    config = load_config(args.config)
    apply_env_overrides(config)  # Apply environment variables first
    apply_overrides(config, args)  # CLI args override env vars

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

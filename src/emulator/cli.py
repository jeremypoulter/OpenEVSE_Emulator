"""
Command-line interface argument parsing for OpenEVSE Emulator.

Handles all CLI argument definitions and parsing.
"""

import argparse
from typing import List, Optional


def create_argument_parser() -> argparse.ArgumentParser:
    """
    Create and configure the argument parser for the emulator.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        description="OpenEVSE Emulator - override config via command line",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start with custom config file
  %(prog)s --config my_config.json

  # Override serial port settings
  %(prog)s --serial-mode tcp --serial-tcp-port 9000

  # Override web UI settings
  %(prog)s --web-host 127.0.0.1 --web-port 9090

  # Override EVSE settings
  %(prog)s --evse-default-current 16 --evse-service-level L1
        """,
    )

    # Config file
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON file (default: config.json)",
    )

    # Serial port options
    parser.add_argument(
        "--serial-mode",
        dest="serial_mode",
        type=str,
        default=argparse.SUPPRESS,
        help="Virtual serial mode: pty or tcp (default: pty)",
    )
    parser.add_argument(
        "--serial-tcp-port",
        dest="serial_tcp_port",
        type=int,
        default=argparse.SUPPRESS,
        help="TCP port for tcp serial mode (default: 8023)",
    )
    parser.add_argument(
        "--serial-baudrate",
        dest="serial_baudrate",
        type=int,
        default=argparse.SUPPRESS,
        help="Serial baud rate (default: 115200)",
    )
    parser.add_argument(
        "--serial-pty-path",
        dest="serial_pty_path",
        type=str,
        default=argparse.SUPPRESS,
        help="Explicit PTY path (e.g. /tmp/rapi_pty_0). If not set, auto-generated.",
    )
    parser.add_argument(
        "--serial-reconnect-timeout",
        dest="serial_reconnect_timeout",
        type=int,
        default=argparse.SUPPRESS,
        help="Max seconds to retry connections (0=infinite, default: 60)",
    )
    parser.add_argument(
        "--serial-reconnect-backoff",
        dest="serial_reconnect_backoff",
        type=int,
        default=argparse.SUPPRESS,
        help="Initial backoff between connection retries in ms (default: 1000)",
    )

    # EVSE options
    parser.add_argument(
        "--evse-firmware-version",
        dest="evse_firmware_version",
        type=str,
        default=argparse.SUPPRESS,
        help="EVSE firmware version string reported to RAPI clients",
    )
    parser.add_argument(
        "--evse-protocol-version",
        dest="evse_protocol_version",
        type=str,
        default=argparse.SUPPRESS,
        help="EVSE RAPI protocol version string",
    )
    parser.add_argument(
        "--evse-default-current",
        dest="evse_default_current",
        type=int,
        default=argparse.SUPPRESS,
        help="Default EVSE current capacity in amps (e.g. 32)",
    )
    parser.add_argument(
        "--evse-service-level",
        dest="evse_service_level",
        choices=["L1", "L2", "Auto"],
        default=argparse.SUPPRESS,
        help="EVSE service level: L1, L2, or Auto",
    )
    parser.add_argument(
        "--evse-gfci-self-test",
        dest="evse_gfci_self_test",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Enable GFCI self-test at boot",
    )

    # EV options
    parser.add_argument(
        "--ev-battery-capacity-kwh",
        dest="ev_battery_capacity_kwh",
        type=float,
        default=argparse.SUPPRESS,
        help="Simulated EV battery capacity in kWh",
    )
    parser.add_argument(
        "--ev-max-charge-rate-kw",
        dest="ev_max_charge_rate_kw",
        type=float,
        default=argparse.SUPPRESS,
        help="Simulated EV max charge rate in kW",
    )

    # Web UI options
    parser.add_argument(
        "--web-host",
        dest="web_host",
        type=str,
        default=argparse.SUPPRESS,
        help="Web UI bind address (e.g. 0.0.0.0 or 127.0.0.1)",
    )
    parser.add_argument(
        "--web-port",
        dest="web_port",
        type=int,
        default=argparse.SUPPRESS,
        help="Web UI HTTP port (default: 8080)",
    )

    # Simulation options
    parser.add_argument(
        "--simulation-update-interval-ms",
        dest="simulation_update_interval_ms",
        type=int,
        default=argparse.SUPPRESS,
        help="Simulation loop update interval in milliseconds",
    )
    parser.add_argument(
        "--simulation-temperature-simulation",
        dest="simulation_temperature_simulation",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Simulate EVSE temperature changes during charging",
    )
    parser.add_argument(
        "--simulation-realistic-charge-curve",
        dest="simulation_realistic_charge_curve",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Use a realistic EV charge curve (taper near full SOC)",
    )

    return parser


def parse_arguments(args: Optional[List[str]] = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        args: Optional list of arguments to parse. If None, uses sys.argv.

    Returns:
        Parsed arguments namespace

    Example:
        >>> args = parse_arguments(['--web-port', '9090'])
        >>> args.web_port
        9090
    """
    parser = create_argument_parser()
    return parser.parse_args(args)

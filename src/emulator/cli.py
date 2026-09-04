"""
Command-line interface argument parsing for OpenEVSE Emulator.

Handles all CLI argument definitions and parsing.
"""

import argparse
from typing import List, Optional

from .config import SUPPORTED_FIRMWARE_VERSIONS


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
        help="Virtual serial mode: pty, tcp, or device (default: pty)",
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
        "--serial-device",
        dest="serial_device",
        type=str,
        default=argparse.SUPPRESS,
        help=(
            "Path to a real hardware serial device for device mode "
            "(e.g. /dev/ttyUSB0)"
        ),
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
        choices=SUPPORTED_FIRMWARE_VERSIONS,
        default=argparse.SUPPRESS,
        help="EVSE firmware version to emulate (application default: 8.2.3)",
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

    parser.add_argument(
        "--ev-range-km-at-full",
        dest="ev_range_km_at_full",
        type=float,
        default=argparse.SUPPRESS,
        help="Simulated EV driving range in km at 100%% SOC",
    )
    parser.add_argument(
        "--ev-charge-limit-soc",
        dest="ev_charge_limit_soc",
        type=float,
        default=argparse.SUPPRESS,
        help="SOC percentage at which the simulated EV stops charging",
    )

    # Vehicle telemetry reporting options. The target OpenEVSE must have its
    # vehicle_data_src set to 3 (HTTP) or 2 (MQTT) to accept these pushes.
    parser.add_argument(
        "--reporting-interval",
        dest="reporting_interval",
        type=float,
        default=argparse.SUPPRESS,
        help="Seconds between vehicle telemetry pushes (default: 30)",
    )
    parser.add_argument(
        "--reporting-http",
        dest="reporting_http_enabled",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Push vehicle telemetry to an OpenEVSE via POST /status",
    )
    parser.add_argument(
        "--reporting-http-url",
        dest="reporting_http_url",
        type=str,
        default=argparse.SUPPRESS,
        help="OpenEVSE base URL for telemetry push (e.g. http://openevse.local)",
    )
    parser.add_argument(
        "--reporting-http-username",
        dest="reporting_http_username",
        type=str,
        default=argparse.SUPPRESS,
        help="OpenEVSE HTTP basic auth username",
    )
    parser.add_argument(
        "--reporting-http-password",
        dest="reporting_http_password",
        type=str,
        default=argparse.SUPPRESS,
        help="OpenEVSE HTTP basic auth password",
    )
    parser.add_argument(
        "--reporting-mqtt",
        dest="reporting_mqtt_enabled",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Publish vehicle telemetry to an MQTT broker",
    )
    parser.add_argument(
        "--reporting-mqtt-host",
        dest="reporting_mqtt_host",
        type=str,
        default=argparse.SUPPRESS,
        help="MQTT broker hostname for telemetry publishing",
    )
    parser.add_argument(
        "--reporting-mqtt-port",
        dest="reporting_mqtt_port",
        type=int,
        default=argparse.SUPPRESS,
        help="MQTT broker port (default: 1883)",
    )
    parser.add_argument(
        "--reporting-mqtt-username",
        dest="reporting_mqtt_username",
        type=str,
        default=argparse.SUPPRESS,
        help="MQTT broker username",
    )
    parser.add_argument(
        "--reporting-mqtt-password",
        dest="reporting_mqtt_password",
        type=str,
        default=argparse.SUPPRESS,
        help="MQTT broker password",
    )
    parser.add_argument(
        "--reporting-mqtt-topic-prefix",
        dest="reporting_mqtt_topic_prefix",
        type=str,
        default=argparse.SUPPRESS,
        help="MQTT topic prefix for telemetry (default: emulator/vehicle)",
    )
    parser.add_argument(
        "--reporting-http-timeout",
        dest="reporting_http_timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="HTTP request timeout in seconds for telemetry push (default: 5)",
    )
    parser.add_argument(
        "--reporting-mqtt-retain",
        dest="reporting_mqtt_retain",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="Publish telemetry as retained MQTT messages (default: on)",
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

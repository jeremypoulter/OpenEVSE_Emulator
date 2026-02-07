"""Tests for CLI argument parsing."""

import argparse
import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from emulator.cli import create_argument_parser, parse_arguments


def test_create_argument_parser():
    """Test that argument parser is created correctly."""
    parser = create_argument_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    assert "OpenEVSE Emulator" in parser.description


def test_parse_arguments_no_args():
    """Test parsing with no arguments uses defaults."""
    args = parse_arguments([])
    # --config has a default value
    assert args.config == "config.json"
    # Other args should not be present (SUPPRESS default)
    assert not hasattr(args, "web_port")
    assert not hasattr(args, "serial_mode")


def test_parse_arguments_config_file():
    """Test parsing config file path."""
    args = parse_arguments(["--config", "custom_config.json"])
    assert args.config == "custom_config.json"


def test_parse_arguments_serial_mode():
    """Test parsing serial mode arguments."""
    args = parse_arguments(["--serial-mode", "tcp"])
    assert args.serial_mode == "tcp"


def test_parse_arguments_serial_tcp_port():
    """Test parsing serial TCP port."""
    args = parse_arguments(["--serial-tcp-port", "9000"])
    assert args.serial_tcp_port == 9000
    assert isinstance(args.serial_tcp_port, int)


def test_parse_arguments_serial_baudrate():
    """Test parsing serial baudrate."""
    args = parse_arguments(["--serial-baudrate", "57600"])
    assert args.serial_baudrate == 57600


def test_parse_arguments_serial_pty_path():
    """Test parsing serial PTY path."""
    args = parse_arguments(["--serial-pty-path", "/tmp/test_pty"])
    assert args.serial_pty_path == "/tmp/test_pty"


def test_parse_arguments_serial_reconnect_timeout():
    """Test parsing serial reconnect timeout."""
    args = parse_arguments(["--serial-reconnect-timeout", "120"])
    assert args.serial_reconnect_timeout == 120


def test_parse_arguments_serial_reconnect_backoff():
    """Test parsing serial reconnect backoff."""
    args = parse_arguments(["--serial-reconnect-backoff", "2000"])
    assert args.serial_reconnect_backoff == 2000


def test_parse_arguments_evse_firmware_version():
    """Test parsing EVSE firmware version."""
    args = parse_arguments(["--evse-firmware-version", "9.0.0"])
    assert args.evse_firmware_version == "9.0.0"


def test_parse_arguments_evse_protocol_version():
    """Test parsing EVSE protocol version."""
    args = parse_arguments(["--evse-protocol-version", "6.0.0"])
    assert args.evse_protocol_version == "6.0.0"


def test_parse_arguments_evse_default_current():
    """Test parsing EVSE default current."""
    args = parse_arguments(["--evse-default-current", "16"])
    assert args.evse_default_current == 16
    assert isinstance(args.evse_default_current, int)


def test_parse_arguments_evse_service_level():
    """Test parsing EVSE service level."""
    args = parse_arguments(["--evse-service-level", "L1"])
    assert args.evse_service_level == "L1"

    args = parse_arguments(["--evse-service-level", "L2"])
    assert args.evse_service_level == "L2"

    args = parse_arguments(["--evse-service-level", "Auto"])
    assert args.evse_service_level == "Auto"


def test_parse_arguments_evse_service_level_invalid():
    """Test that invalid service level is rejected."""
    with pytest.raises(SystemExit):
        parse_arguments(["--evse-service-level", "L3"])


def test_parse_arguments_evse_gfci_self_test():
    """Test parsing EVSE GFCI self-test flag."""
    # Enable
    args = parse_arguments(["--evse-gfci-self-test"])
    assert args.evse_gfci_self_test is True

    # Disable
    args = parse_arguments(["--no-evse-gfci-self-test"])
    assert args.evse_gfci_self_test is False


def test_parse_arguments_ev_battery_capacity():
    """Test parsing EV battery capacity."""
    args = parse_arguments(["--ev-battery-capacity-kwh", "85.5"])
    assert args.ev_battery_capacity_kwh == 85.5
    assert isinstance(args.ev_battery_capacity_kwh, float)


def test_parse_arguments_ev_max_charge_rate():
    """Test parsing EV max charge rate."""
    args = parse_arguments(["--ev-max-charge-rate-kw", "11.5"])
    assert args.ev_max_charge_rate_kw == 11.5
    assert isinstance(args.ev_max_charge_rate_kw, float)


def test_parse_arguments_web_host():
    """Test parsing web host."""
    args = parse_arguments(["--web-host", "127.0.0.1"])
    assert args.web_host == "127.0.0.1"


def test_parse_arguments_web_port():
    """Test parsing web port."""
    args = parse_arguments(["--web-port", "9090"])
    assert args.web_port == 9090
    assert isinstance(args.web_port, int)


def test_parse_arguments_simulation_update_interval():
    """Test parsing simulation update interval."""
    args = parse_arguments(["--simulation-update-interval-ms", "500"])
    assert args.simulation_update_interval_ms == 500


def test_parse_arguments_simulation_temperature_simulation():
    """Test parsing simulation temperature flag."""
    # Enable
    args = parse_arguments(["--simulation-temperature-simulation"])
    assert args.simulation_temperature_simulation is True

    # Disable
    args = parse_arguments(["--no-simulation-temperature-simulation"])
    assert args.simulation_temperature_simulation is False


def test_parse_arguments_simulation_realistic_charge_curve():
    """Test parsing realistic charge curve flag."""
    # Enable
    args = parse_arguments(["--simulation-realistic-charge-curve"])
    assert args.simulation_realistic_charge_curve is True

    # Disable
    args = parse_arguments(["--no-simulation-realistic-charge-curve"])
    assert args.simulation_realistic_charge_curve is False


def test_parse_arguments_multiple_options():
    """Test parsing multiple options together."""
    args = parse_arguments(
        [
            "--config",
            "test.json",
            "--serial-mode",
            "tcp",
            "--serial-tcp-port",
            "9000",
            "--web-port",
            "8888",
            "--evse-default-current",
            "24",
        ]
    )

    assert args.config == "test.json"
    assert args.serial_mode == "tcp"
    assert args.serial_tcp_port == 9000
    assert args.web_port == 8888
    assert args.evse_default_current == 24


def test_parse_arguments_type_validation():
    """Test that type validation works correctly."""
    # Invalid integer for port
    with pytest.raises(SystemExit):
        parse_arguments(["--web-port", "not_a_number"])

    # Invalid float for battery capacity
    with pytest.raises(SystemExit):
        parse_arguments(["--ev-battery-capacity-kwh", "invalid"])


def test_parse_arguments_help():
    """Test that help flag exits properly."""
    with pytest.raises(SystemExit) as exc_info:
        parse_arguments(["--help"])
    # Help exits with code 0
    assert exc_info.value.code == 0


def test_argument_destinations():
    """Test that argument destinations use underscores correctly."""
    args = parse_arguments(
        [
            "--serial-mode",
            "tcp",
            "--evse-service-level",
            "L2",
            "--web-host",
            "localhost",
        ]
    )

    # Verify destinations use underscores
    assert hasattr(args, "serial_mode")
    assert hasattr(args, "evse_service_level")
    assert hasattr(args, "web_host")

    # Not hyphens
    assert not hasattr(args, "serial-mode")
    assert not hasattr(args, "evse-service-level")
    assert not hasattr(args, "web-host")


def test_suppress_default_behavior():
    """Test that SUPPRESS default prevents attributes from being set."""
    args = parse_arguments([])

    # Only config should be present (has explicit default)
    assert hasattr(args, "config")

    # These should not be present due to SUPPRESS
    assert not hasattr(args, "serial_mode")
    assert not hasattr(args, "web_port")
    assert not hasattr(args, "evse_default_current")
    assert not hasattr(args, "simulation_update_interval_ms")


def test_all_serial_options():
    """Test all serial-related options together."""
    args = parse_arguments(
        [
            "--serial-mode",
            "tcp",
            "--serial-tcp-port",
            "9999",
            "--serial-baudrate",
            "9600",
            "--serial-pty-path",
            "/tmp/pty",
            "--serial-reconnect-timeout",
            "30",
            "--serial-reconnect-backoff",
            "500",
        ]
    )

    assert args.serial_mode == "tcp"
    assert args.serial_tcp_port == 9999
    assert args.serial_baudrate == 9600
    assert args.serial_pty_path == "/tmp/pty"
    assert args.serial_reconnect_timeout == 30
    assert args.serial_reconnect_backoff == 500


def test_all_evse_options():
    """Test all EVSE-related options together."""
    args = parse_arguments(
        [
            "--evse-firmware-version",
            "10.0.0",
            "--evse-protocol-version",
            "7.0.0",
            "--evse-default-current",
            "48",
            "--evse-service-level",
            "Auto",
            "--evse-gfci-self-test",
        ]
    )

    assert args.evse_firmware_version == "10.0.0"
    assert args.evse_protocol_version == "7.0.0"
    assert args.evse_default_current == 48
    assert args.evse_service_level == "Auto"
    assert args.evse_gfci_self_test is True


def test_all_ev_options():
    """Test all EV-related options together."""
    args = parse_arguments(
        [
            "--ev-battery-capacity-kwh",
            "100.5",
            "--ev-max-charge-rate-kw",
            "22.0",
        ]
    )

    assert args.ev_battery_capacity_kwh == 100.5
    assert args.ev_max_charge_rate_kw == 22.0


def test_all_web_options():
    """Test all web-related options together."""
    args = parse_arguments(["--web-host", "0.0.0.0", "--web-port", "7777"])

    assert args.web_host == "0.0.0.0"
    assert args.web_port == 7777


def test_all_simulation_options():
    """Test all simulation-related options together."""
    args = parse_arguments(
        [
            "--simulation-update-interval-ms",
            "2000",
            "--simulation-temperature-simulation",
            "--simulation-realistic-charge-curve",
        ]
    )

    assert args.simulation_update_interval_ms == 2000
    assert args.simulation_temperature_simulation is True
    assert args.simulation_realistic_charge_curve is True


def test_parser_description():
    """Test that parser has appropriate description."""
    parser = create_argument_parser()
    assert parser.description is not None
    assert len(parser.description) > 0
    assert "OpenEVSE" in parser.description


def test_parser_has_all_expected_arguments():
    """Test that parser has all expected argument groups."""
    parser = create_argument_parser()

    # Get all argument destinations
    dests = [action.dest for action in parser._actions if action.dest != "help"]

    # Check key arguments are present
    expected_dests = [
        "config",
        "serial_mode",
        "serial_tcp_port",
        "evse_firmware_version",
        "evse_default_current",
        "evse_service_level",
        "ev_battery_capacity_kwh",
        "web_host",
        "web_port",
        "simulation_update_interval_ms",
    ]

    for dest in expected_dests:
        assert dest in dests, f"Expected argument destination '{dest}' not found"

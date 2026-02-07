"""
Configuration management for OpenEVSE Emulator.

Handles loading, merging, and overriding configuration from multiple sources:
1. Default configuration
2. JSON configuration files
3. Environment variables
4. Command-line arguments
"""

import json
import os
import sys
from typing import Any


def default_config() -> dict:
    """Return default configuration."""
    return {
        "serial": {
            "mode": "pty",
            "tcp_port": 8023,
            "baudrate": 115200,
            "pty_path": None,  # None = auto-generate, or explicit path
            "reconnect_timeout_sec": 60,  # Max time to retry connections (0 = infinite)
            "reconnect_backoff_ms": 1000,  # Initial backoff between retries
        },
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
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to JSON configuration file

    Returns:
        Configuration dictionary

    Raises:
        SystemExit: If config file has invalid JSON
    """
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Config file {config_path} not found, using defaults")
        return default_config()
    except json.JSONDecodeError as e:
        print(f"Error parsing config file: {e}")
        sys.exit(1)


def set_nested(config: dict, dot_path: str, value: Any) -> None:
    """
    Set a nested dictionary key from a dot-separated path.

    Args:
        config: Configuration dictionary to modify
        dot_path: Dot-separated path (e.g., 'serial.tcp_port')
        value: Value to set

    Example:
        >>> config = {}
        >>> set_nested(config, 'serial.tcp_port', 8024)
        >>> config
        {'serial': {'tcp_port': 8024}}
    """
    parts = dot_path.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def get_nested(config: dict, dot_path: str, default: Any = None) -> Any:
    """
    Get a value from a nested dictionary using a dot-separated path.

    Args:
        config: Configuration dictionary
        dot_path: Dot-separated path (e.g., 'serial.tcp_port')
        default: Default value if path doesn't exist

    Returns:
        Value at the path, or default if not found

    Example:
        >>> config = {'serial': {'tcp_port': 8023}}
        >>> get_nested(config, 'serial.tcp_port')
        8023
        >>> get_nested(config, 'serial.invalid', 'default')
        'default'
    """
    parts = dot_path.split(".")
    current = config
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


# Mapping from environment variable names to config dot paths.
ENV_OVERRIDE_PATHS = {
    "SERIAL_MODE": "serial.mode",
    "SERIAL_TCP_PORT": "serial.tcp_port",
    "SERIAL_PTY_PATH": "serial.pty_path",
    "SERIAL_RECONNECT_TIMEOUT": "serial.reconnect_timeout_sec",
    "SERIAL_RECONNECT_BACKOFF": "serial.reconnect_backoff_ms",
    "WEB_HOST": "web.host",
    "WEB_PORT": "web.port",
}

# Explicit type mapping for environment variable overrides
ENV_OVERRIDE_TYPES = {
    "serial.tcp_port": int,
    "serial.reconnect_timeout_sec": int,
    "serial.reconnect_backoff_ms": int,
    "web.port": int,
}


def apply_env_overrides(config: dict, verbose: bool = True) -> None:
    """
    Apply environment variable overrides to configuration.

    Environment variables override configuration file values.
    Supported variables are defined in ENV_OVERRIDE_PATHS.

    Args:
        config: Configuration dictionary to modify in-place
        verbose: Whether to print messages about applied overrides

    Example:
        >>> os.environ['WEB_PORT'] = '9090'
        >>> config = default_config()
        >>> apply_env_overrides(config, verbose=False)
        >>> config['web']['port']
        9090
    """
    for env_var, dot_path in ENV_OVERRIDE_PATHS.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Type conversion based on explicit type mapping
            converter = None
            last_segment = dot_path.split(".")[-1]
            for key in (dot_path, last_segment, env_var):
                if key in ENV_OVERRIDE_TYPES:
                    converter = ENV_OVERRIDE_TYPES[key]
                    break

            if converter is not None:
                try:
                    value = converter(value)
                except (ValueError, TypeError):
                    type_name = getattr(converter, "__name__", type(converter).__name__)
                    if verbose:
                        print(
                            f"Warning: Invalid {type_name} value for "
                            f"{env_var}={value}, skipping"
                        )
                    continue

            set_nested(config, dot_path, value)
            if verbose:
                print(f"Applied env override: {env_var} -> {dot_path}")


# Mapping from CLI argument names to config dot paths
CLI_OVERRIDE_PATHS = {
    "serial_mode": "serial.mode",
    "serial_tcp_port": "serial.tcp_port",
    "serial_baudrate": "serial.baudrate",
    "serial_pty_path": "serial.pty_path",
    "serial_reconnect_timeout": "serial.reconnect_timeout_sec",
    "serial_reconnect_backoff": "serial.reconnect_backoff_ms",
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
}


def apply_cli_overrides(config: dict, args: dict) -> None:
    """
    Apply command-line argument overrides to configuration.

    CLI arguments override both config file and environment variables.

    Args:
        config: Configuration dictionary to modify in-place
        args: Dictionary of argument names to values (e.g., from argparse Namespace)

    Example:
        >>> config = default_config()
        >>> args = {'web_port': 9090}
        >>> apply_cli_overrides(config, args)
        >>> config['web']['port']
        9090
    """
    for dest, dot_path in CLI_OVERRIDE_PATHS.items():
        if dest in args and args[dest] is not None:
            set_nested(config, dot_path, args[dest])


def merge_config(
    base_config: dict,
    overrides: dict,
) -> dict:
    """
    Merge override configuration into base configuration.

    Creates a new dictionary without modifying the originals.
    Override values take precedence over base values.

    Args:
        base_config: Base configuration dictionary
        overrides: Override configuration dictionary

    Returns:
        New merged configuration dictionary

    Example:
        >>> base = {'web': {'host': '0.0.0.0', 'port': 8080}}
        >>> override = {'web': {'port': 9090}}
        >>> result = merge_config(base, override)
        >>> result['web']['port']
        9090
        >>> result['web']['host']
        '0.0.0.0'
    """
    result = {}
    for key in set(base_config.keys()) | set(overrides.keys()):
        if key in overrides and key in base_config:
            if isinstance(base_config[key], dict) and isinstance(overrides[key], dict):
                # Recursively merge nested dicts
                result[key] = merge_config(base_config[key], overrides[key])
            else:
                # Override takes precedence
                result[key] = overrides[key]
        elif key in overrides:
            result[key] = overrides[key]
        else:
            result[key] = base_config[key]
    return result

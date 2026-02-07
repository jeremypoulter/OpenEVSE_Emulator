"""Tests for configuration management."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from emulator.config import (
    CLI_OVERRIDE_PATHS,
    ENV_OVERRIDE_PATHS,
    ENV_OVERRIDE_TYPES,
    apply_cli_overrides,
    apply_env_overrides,
    default_config,
    get_nested,
    load_config,
    merge_config,
    set_nested,
)


def test_default_config():
    """Test default configuration structure."""
    config = default_config()

    # Check top-level keys
    assert "serial" in config
    assert "evse" in config
    assert "ev" in config
    assert "web" in config
    assert "simulation" in config

    # Check serial config
    assert config["serial"]["mode"] == "pty"
    assert config["serial"]["tcp_port"] == 8023
    assert config["serial"]["baudrate"] == 115200
    assert config["serial"]["pty_path"] is None

    # Check EVSE config
    assert config["evse"]["firmware_version"] == "8.2.1"
    assert config["evse"]["protocol_version"] == "5.0.1"
    assert config["evse"]["default_current"] == 32

    # Check web config
    assert config["web"]["host"] == "0.0.0.0"
    assert config["web"]["port"] == 8080


def test_set_nested():
    """Test setting nested dictionary values."""
    config = {}

    # Set a simple nested value
    set_nested(config, "serial.tcp_port", 8024)
    assert config == {"serial": {"tcp_port": 8024}}

    # Set another value in the same nested dict
    set_nested(config, "serial.mode", "tcp")
    assert config == {"serial": {"tcp_port": 8024, "mode": "tcp"}}

    # Set a deeply nested value
    set_nested(config, "a.b.c.d", "value")
    assert config["a"]["b"]["c"]["d"] == "value"


def test_get_nested():
    """Test getting nested dictionary values."""
    config = {"serial": {"tcp_port": 8023, "mode": "pty"}, "web": {"port": 8080}}

    # Get existing values
    assert get_nested(config, "serial.tcp_port") == 8023
    assert get_nested(config, "serial.mode") == "pty"
    assert get_nested(config, "web.port") == 8080

    # Get non-existent values
    assert get_nested(config, "invalid.path") is None
    assert get_nested(config, "invalid.path", "default") == "default"
    assert get_nested(config, "serial.invalid") is None

    # Get from partial path
    assert get_nested(config, "serial") == {"tcp_port": 8023, "mode": "pty"}


def test_load_config_from_file():
    """Test loading configuration from a JSON file."""
    test_config = {"serial": {"mode": "tcp", "tcp_port": 9999}, "web": {"port": 7777}}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(test_config, f)
        temp_path = f.name

    try:
        config = load_config(temp_path)
        assert config["serial"]["mode"] == "tcp"
        assert config["serial"]["tcp_port"] == 9999
        assert config["web"]["port"] == 7777
    finally:
        os.unlink(temp_path)


def test_load_config_file_not_found():
    """Test loading config when file doesn't exist returns defaults."""
    config = load_config("/nonexistent/path/config.json")
    # Should return default config
    assert config == default_config()


def test_load_config_invalid_json():
    """Test loading config with invalid JSON exits."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{ invalid json }")
        temp_path = f.name

    try:
        with pytest.raises(SystemExit):
            load_config(temp_path)
    finally:
        os.unlink(temp_path)


def test_apply_env_overrides(monkeypatch):
    """Test applying environment variable overrides."""
    config = default_config()

    # Set environment variables
    monkeypatch.setenv("SERIAL_MODE", "tcp")
    monkeypatch.setenv("SERIAL_TCP_PORT", "9999")
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_PORT", "7777")

    apply_env_overrides(config, verbose=False)

    # Check values were applied
    assert config["serial"]["mode"] == "tcp"
    assert config["serial"]["tcp_port"] == 9999
    assert config["web"]["host"] == "127.0.0.1"
    assert config["web"]["port"] == 7777


def test_apply_env_overrides_type_conversion(monkeypatch):
    """Test that environment variables are converted to correct types."""
    config = default_config()

    # Set integer environment variables as strings
    monkeypatch.setenv("WEB_PORT", "9090")
    monkeypatch.setenv("SERIAL_TCP_PORT", "8888")

    apply_env_overrides(config, verbose=False)

    # Check they're converted to integers
    assert isinstance(config["web"]["port"], int)
    assert config["web"]["port"] == 9090
    assert isinstance(config["serial"]["tcp_port"], int)
    assert config["serial"]["tcp_port"] == 8888


def test_apply_env_overrides_invalid_type(monkeypatch, capsys):
    """Test that invalid type conversions are handled gracefully."""
    config = default_config()
    original_port = config["web"]["port"]

    # Set invalid integer value
    monkeypatch.setenv("WEB_PORT", "not_a_number")

    apply_env_overrides(config, verbose=True)

    # Should print warning and skip the invalid value
    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert "WEB_PORT" in captured.out

    # Original value should be unchanged
    assert config["web"]["port"] == original_port


def test_apply_env_overrides_verbose_output(monkeypatch, capsys):
    """Test verbose output when applying env overrides."""
    config = default_config()
    monkeypatch.setenv("SERIAL_MODE", "tcp")

    apply_env_overrides(config, verbose=True)

    captured = capsys.readouterr()
    assert "Applied env override: SERIAL_MODE -> serial.mode" in captured.out


def test_apply_cli_overrides():
    """Test applying CLI argument overrides."""
    config = default_config()

    args = {
        "serial_mode": "tcp",
        "serial_tcp_port": 9999,
        "web_host": "127.0.0.1",
        "web_port": 7777,
        "evse_firmware_version": "9.0.0",
    }

    apply_cli_overrides(config, args)

    assert config["serial"]["mode"] == "tcp"
    assert config["serial"]["tcp_port"] == 9999
    assert config["web"]["host"] == "127.0.0.1"
    assert config["web"]["port"] == 7777
    assert config["evse"]["firmware_version"] == "9.0.0"


def test_apply_cli_overrides_none_values():
    """Test that None values in CLI args are ignored."""
    config = default_config()
    original_port = config["web"]["port"]

    args = {"web_port": None, "serial_mode": "tcp"}

    apply_cli_overrides(config, args)

    # None value should not override
    assert config["web"]["port"] == original_port
    # Valid value should override
    assert config["serial"]["mode"] == "tcp"


def test_merge_config_simple():
    """Test merging simple configurations."""
    base = {"web": {"host": "0.0.0.0", "port": 8080}}
    override = {"web": {"port": 9090}}

    result = merge_config(base, override)

    # Port should be overridden
    assert result["web"]["port"] == 9090
    # Host should remain from base
    assert result["web"]["host"] == "0.0.0.0"

    # Originals should be unchanged
    assert base["web"]["port"] == 8080


def test_merge_config_nested():
    """Test merging deeply nested configurations."""
    base = {
        "serial": {"mode": "pty", "tcp_port": 8023, "baudrate": 115200},
        "web": {"host": "0.0.0.0", "port": 8080},
    }
    override = {
        "serial": {"mode": "tcp", "tcp_port": 9999},
        "new_section": {"value": "test"},
    }

    result = merge_config(base, override)

    # Overridden values
    assert result["serial"]["mode"] == "tcp"
    assert result["serial"]["tcp_port"] == 9999
    # Base values preserved
    assert result["serial"]["baudrate"] == 115200
    assert result["web"]["host"] == "0.0.0.0"
    # New section added
    assert result["new_section"]["value"] == "test"


def test_merge_config_non_dict_override():
    """Test that non-dict values override completely."""
    base = {"value": {"nested": "data"}}
    override = {"value": "string"}

    result = merge_config(base, override)

    # Override should replace entire dict with string
    assert result["value"] == "string"


def test_env_override_paths_coverage():
    """Test that all ENV_OVERRIDE_PATHS are valid."""
    config = default_config()

    # All paths should exist in default config (even if value is None)
    for env_var, dot_path in ENV_OVERRIDE_PATHS.items():
        # Use a sentinel to distinguish "not found" from None
        sentinel = object()
        value = get_nested(config, dot_path, sentinel)
        assert (
            value is not sentinel
        ), f"Path {dot_path} for {env_var} not in default config"


def test_cli_override_paths_coverage():
    """Test that all CLI_OVERRIDE_PATHS are valid."""
    config = default_config()

    # All paths should exist in default config or be creatable
    for arg_name, dot_path in CLI_OVERRIDE_PATHS.items():
        # Set a test value
        set_nested(config, dot_path, "test")
        value = get_nested(config, dot_path)
        assert value == "test", f"Path {dot_path} for {arg_name} not settable"


def test_env_override_types_all_defined():
    """Test that all integer type conversions are defined."""
    # All paths that need int conversion should be in ENV_OVERRIDE_TYPES
    int_paths = [
        "serial.tcp_port",
        "serial.reconnect_timeout_sec",
        "serial.reconnect_backoff_ms",
        "web.port",
    ]

    for path in int_paths:
        assert (
            path in ENV_OVERRIDE_TYPES
        ), f"Integer path {path} missing from ENV_OVERRIDE_TYPES"
        assert ENV_OVERRIDE_TYPES[path] == int


def test_config_override_precedence(monkeypatch):
    """Test that overrides apply in correct order: file < env < cli."""
    # Start with file config
    config = {"web": {"port": 8080, "host": "0.0.0.0"}}

    # Apply env override
    monkeypatch.setenv("WEB_PORT", "9090")
    apply_env_overrides(config, verbose=False)
    assert config["web"]["port"] == 9090

    # Apply CLI override (should take precedence)
    args = {"web_port": 7777}
    apply_cli_overrides(config, args)
    assert config["web"]["port"] == 7777


def test_set_nested_creates_intermediate_dicts():
    """Test that set_nested creates intermediate dictionaries."""
    config = {}
    set_nested(config, "a.b.c.d.e", "value")

    assert config["a"]["b"]["c"]["d"]["e"] == "value"
    assert isinstance(config["a"], dict)
    assert isinstance(config["a"]["b"], dict)
    assert isinstance(config["a"]["b"]["c"], dict)


def test_get_nested_with_non_dict_intermediate():
    """Test get_nested when intermediate value is not a dict."""
    config = {"a": {"b": "not_a_dict"}}

    # Should return default when path goes through non-dict
    result = get_nested(config, "a.b.c", "default")
    assert result == "default"

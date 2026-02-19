"""Tests for EV simulator."""

import pytest

from src.emulator.ev import EVSimulator


def test_ev_initialization():
    """Test EV initialization."""
    ev = EVSimulator(battery_capacity_kwh=75.0, max_charge_rate_kw=7.2)
    assert ev.battery_capacity_kwh == 75.0
    assert ev.max_charge_rate_kw == 7.2
    assert not ev.connected
    assert not ev.requesting_charge
    assert ev.soc == 50.0


def test_ev_connection():
    """Test EV connection and disconnection."""
    ev = EVSimulator()

    # Connect
    ev.connected = True
    assert ev.connected

    # Request charge while connected
    ev.requesting_charge = True
    assert ev.requesting_charge

    # Disconnect should stop charge request
    ev.connected = False
    assert not ev.connected
    assert not ev.requesting_charge


def test_ev_soc_bounds():
    """Test battery SoC bounds."""
    ev = EVSimulator()

    # Set to 150% (should cap at 100%)
    ev.soc = 150.0
    assert ev.soc == 100.0

    # Set to -10% (should cap at 0%)
    ev.soc = -10.0
    assert ev.soc == 0.0


def test_pilot_resistance_states():
    """Test J1772 pilot resistance states."""
    ev = EVSimulator()

    # State A: Not connected
    assert ev.get_pilot_resistance() == "A"

    # State B: Connected, not charging
    ev.connected = True
    assert ev.get_pilot_resistance() == "B"

    # State C: Charging (needs actual charge rate)
    ev.requesting_charge = True
    ev.update_charging(32, 240, 1.0)
    assert ev.get_pilot_resistance() == "C"

    # State D: Diode check failed
    ev.diode_check_failed = True
    assert ev.get_pilot_resistance() == "D"


def test_charging_simulation():
    """Test charging simulation updates SoC."""
    ev = EVSimulator(battery_capacity_kwh=75.0, max_charge_rate_kw=7.2)
    ev.connected = True
    ev.requesting_charge = True
    ev.soc = 50.0

    initial_soc = ev.soc

    # Simulate 1 hour of charging at 7.2kW
    # Should add 7.2kWh / 75kWh * 100 = 9.6%
    ev.update_charging(30, 240, 3600)

    assert ev.soc > initial_soc
    assert ev.actual_charge_rate_kw > 0


def test_charging_stops_at_full():
    """Test charging stops when battery is full."""
    ev = EVSimulator(battery_capacity_kwh=10.0, max_charge_rate_kw=10.0)
    ev.connected = True
    ev.requesting_charge = True
    ev.soc = 99.9

    # Charge for enough time to go over 100%
    ev.update_charging(50, 240, 3600)

    # SoC should be capped at 100%
    assert ev.soc == 100.0

    # Should no longer be requesting charge
    assert not ev.requesting_charge


def test_get_status():
    """Test getting EV status."""
    ev = EVSimulator()
    ev.connected = True
    ev.soc = 75.5

    status = ev.get_status()

    assert status["connected"] is True
    assert status["soc"] == 75.5
    assert "actual_charge_rate_kw" in status
    assert "battery_capacity_kwh" in status


def test_diode_check_failed_property():
    """Test diode check failed property getter and setter."""
    ev = EVSimulator()

    # Initially False
    assert ev.diode_check_failed is False

    # Set to True
    ev.diode_check_failed = True
    assert ev.diode_check_failed is True

    # Should affect pilot resistance
    ev.connected = True
    assert ev.get_pilot_resistance() == "D"

    # Reset
    ev.diode_check_failed = False
    assert ev.get_pilot_resistance() == "B"


def test_charging_stops_at_full_no_power():
    """Test that charging rate becomes 0 when battery is full."""
    ev = EVSimulator(battery_capacity_kwh=10.0, max_charge_rate_kw=10.0)
    ev.connected = True
    ev.requesting_charge = True
    ev.soc = 100.0

    # Try to charge when already full
    ev.update_charging(50, 240, 1.0)

    # Charge rate should be 0
    assert ev.actual_charge_rate_kw == 0.0
    assert ev.soc == 100.0


def test_direct_mode_default():
    """Test direct mode is off by default."""
    ev = EVSimulator()
    assert ev.direct_mode is False
    assert ev.direct_current_amps == 0.0
    assert ev.current_variance_enabled is False


def test_direct_mode_toggle():
    """Test toggling direct control mode."""
    ev = EVSimulator()

    ev.direct_mode = True
    assert ev.direct_mode is True

    ev.direct_mode = False
    assert ev.direct_mode is False


def test_direct_current_setter():
    """Test setting direct current value."""
    ev = EVSimulator()

    ev.direct_current_amps = 16.0
    assert ev.direct_current_amps == 16.0

    # Negative values should be clamped to 0
    ev.direct_current_amps = -5.0
    assert ev.direct_current_amps == 0.0


def test_direct_mode_charging():
    """Test charging in direct control mode uses set current."""
    ev = EVSimulator()
    ev.connected = True
    ev.requesting_charge = True
    ev.direct_mode = True
    ev.direct_current_amps = 20.0

    ev.update_charging(32, 240, 1.0)

    # Should use direct current (20A * 240V / 1000 = 4.8 kW)
    assert ev.actual_charge_rate_kw == pytest.approx(4.8, abs=0.1)


def test_direct_mode_no_soc_change():
    """Test that direct mode does not update battery SoC."""
    ev = EVSimulator()
    ev.connected = True
    ev.requesting_charge = True
    ev.soc = 50.0
    ev.direct_mode = True
    ev.direct_current_amps = 20.0

    ev.update_charging(32, 240, 3600)

    # SoC should not change in direct mode
    assert ev.soc == 50.0


def test_direct_mode_zero_when_not_connected():
    """Test direct mode outputs zero when not connected."""
    ev = EVSimulator()
    ev.direct_mode = True
    ev.direct_current_amps = 20.0

    ev.update_charging(32, 240, 1.0)

    assert ev.actual_charge_rate_kw == 0.0


def test_direct_mode_zero_when_not_requesting():
    """Test direct mode outputs zero when not requesting charge."""
    ev = EVSimulator()
    ev.connected = True
    ev.direct_mode = True
    ev.direct_current_amps = 20.0

    ev.update_charging(32, 240, 1.0)

    assert ev.actual_charge_rate_kw == 0.0


def test_variance_toggle():
    """Test toggling current variance."""
    ev = EVSimulator()

    ev.current_variance_enabled = True
    assert ev.current_variance_enabled is True

    ev.current_variance_enabled = False
    assert ev.current_variance_enabled is False


def test_variance_direct_mode():
    """Test variance in direct mode stays within +/- 1%."""
    ev = EVSimulator()
    ev.connected = True
    ev.requesting_charge = True
    ev.direct_mode = True
    ev.direct_current_amps = 100.0
    ev.current_variance_enabled = True

    # Force variance update by manipulating last_variance_time
    import time

    ev._last_variance_time = time.time() - 2.0

    ev.update_charging(100, 240, 1.0)

    # Expected power without variance: 100 * 240 / 1000 = 24.0 kW
    # With +/- 1% variance: 23.76 to 24.24 kW
    assert 23.7 <= ev.actual_charge_rate_kw <= 24.3


def test_variance_battery_mode():
    """Test variance in battery mode only decreases current."""
    ev = EVSimulator(battery_capacity_kwh=75.0, max_charge_rate_kw=24.0)
    ev.connected = True
    ev.requesting_charge = True
    ev.soc = 50.0
    ev.current_variance_enabled = True

    # Force variance update
    import time

    ev._last_variance_time = time.time() - 2.0

    ev.update_charging(32, 240, 0.001)

    # In battery mode, variance only decreases (multiplier 0.99 to 1.0)
    # Max power without variance: 32 * 240 / 1000 = 7.68 kW
    # (capped by max_charge_rate_kw to 24.0 kW, but 7.68 < 24.0)
    # With -1% variance: up to 7.68 kW, down to 7.603 kW
    assert ev.actual_charge_rate_kw <= 7.68
    assert ev.actual_charge_rate_kw >= 7.68 * 0.99 - 0.01


def test_get_status_includes_new_fields():
    """Test that get_status includes direct mode and variance fields."""
    ev = EVSimulator()
    ev.direct_mode = True
    ev.direct_current_amps = 15.0
    ev.current_variance_enabled = True

    status = ev.get_status()

    assert status["direct_mode"] is True
    assert status["direct_current_amps"] == 15.0
    assert status["current_variance_enabled"] is True

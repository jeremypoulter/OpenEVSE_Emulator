"""Tests for EV simulator."""

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

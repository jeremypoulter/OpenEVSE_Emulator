"""Tests for the simulation step loop in src/main.py."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.emulator.config import load_config  # noqa: E402
from src.main import SIMULATION_STEP_SEC, OpenEVSEEmulator  # noqa: E402


def make_charging_emulator():
    config = load_config(os.path.join(os.path.dirname(__file__), "..", "config.json"))
    emu = OpenEVSEEmulator(config=config)
    emu.ev.connected = True
    emu.ev.requesting_charge = True
    emu.ev.soc = 20.0
    emu.evse.update_state("C")
    return emu


@pytest.fixture
def emulator():
    return make_charging_emulator()


def test_long_advance_matches_one_second_steps(emulator):
    """A long advance is split into steps, so it matches the same time run in 1 s steps."""
    stepped = make_charging_emulator()

    emulator.advance(600)
    for _ in range(600):
        stepped.advance(1)

    assert emulator.ev.soc == pytest.approx(stepped.ev.soc)
    assert (
        emulator.evse.get_status()["session_time"]
        == stepped.evse.get_status()["session_time"]
    )


def test_step_size_is_bounded():
    assert SIMULATION_STEP_SEC <= 1.0


def test_steps_share_the_reset_lock(emulator):
    """Reset and the simulation take the same lock, so they cannot interleave."""
    assert emulator.sim_lock is emulator.web_api.sim_lock

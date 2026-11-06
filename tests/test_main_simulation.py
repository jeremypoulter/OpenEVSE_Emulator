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


def test_catch_up_charges_elapsed_wall_time_at_current_scale():
    """Elapsed wall time is simulated at the scale in effect when it is sampled."""
    import time

    emu = make_charging_emulator()
    emu.web_api.time_scale = 10.0
    emu.last_update_time = time.time() - 1.0
    emu.catch_up()
    assert 10 <= emu.evse.get_status()["session_time"] <= 11


def test_reset_discards_time_not_yet_simulated(monkeypatch):
    """A reset must not charge the time that passed before it."""
    import src.main as main_module

    clock = {"now": 1000.0}
    monkeypatch.setattr(main_module.time, "time", lambda: clock["now"])

    emu = make_charging_emulator()
    emu.web_api.time_scale = 3600.0
    emu.last_update_time = clock["now"] - 60.0  # a minute passed before the reset
    emu._on_reset()
    emu.catch_up()  # no wall-clock time has passed since the reset
    assert emu.evse.get_status()["session_time"] == 0


def test_default_step_interval_keeps_the_ui_responsive():
    """The EV's pilot reaches the EVSE only on a simulation step, so the
    interval is how long a click on Connect or Request Charge waits to take
    effect -- and engine mode needs two steps for each state change. At one
    second that was two to four seconds before the page moved."""
    from src.emulator.config import default_config

    config_json = load_config(
        os.path.join(os.path.dirname(__file__), "..", "config.json")
    )
    assert default_config()["simulation"]["update_interval_ms"] <= 200
    assert config_json["simulation"]["update_interval_ms"] <= 200


@pytest.mark.parametrize(
    "start_result, exit_code",
    [(False, 1), (None, None)],
    ids=["failed-to-start", "ran-and-stopped"],
)
def test_main_exit_status_reflects_whether_the_emulator_started(
    monkeypatch, start_result, exit_code
):
    """A start that failed must not look healthy to Docker or CI."""
    from unittest.mock import MagicMock

    import src.main as main_module

    emulator = MagicMock()
    emulator.start.return_value = start_result
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(main_module, "OpenEVSEEmulator", lambda config: emulator)
    monkeypatch.setattr(main_module.signal, "signal", lambda *args: None)

    if exit_code is None:
        main_module.main()
    else:
        with pytest.raises(SystemExit) as exc:
            main_module.main()
        assert exc.value.code == exit_code


def test_no_offer_through_a_contactor_the_firmware_has_just_opened():
    """The firmware opens the contactor a moment before it announces the new
    state. Until it does, the mirror still says charging; offering the vehicle
    current then would have it draw through an open contactor."""
    from unittest.mock import MagicMock

    emu = make_charging_emulator()
    emu.engine = MagicMock()
    emu.engine.charging_without_contactor.return_value = True
    emu.ev.update_charging = MagicMock()

    emu._step(0.1)

    offered = emu.ev.update_charging.call_args[0][0]
    assert offered == 0


def test_the_firmware_is_given_the_voltage_the_vehicle_charges_at():
    """After an L1 change the vehicle charges at 120 V; the CT feed must use it."""
    from unittest.mock import MagicMock

    emu = make_charging_emulator()
    emu.engine = MagicMock()
    emu.engine.charging_without_contactor.return_value = False
    emu.evse.service_level = "L1"

    emu._step(0.1)

    assert emu.engine.apply_ev.call_args[0][1] == 120.0


def test_the_offer_is_untouched_when_the_contactor_is_fine():
    from unittest.mock import MagicMock

    emu = make_charging_emulator()
    emu.engine = MagicMock()
    emu.engine.charging_without_contactor.return_value = False
    emu.ev.update_charging = MagicMock()

    emu._step(0.1)

    assert emu.ev.update_charging.call_args[0][0] > 0


def _startup_commands(config_level, config_amps, firmware_level, firmware_amps):
    from unittest.mock import MagicMock

    emu = make_charging_emulator()
    emu.config["evse"].update(service_level=config_level, default_current=config_amps)
    emu.engine = MagicMock()
    emu.engine.service_level = firmware_level
    emu.engine.current_capacity = firmware_amps
    emu.engine.command.return_value = (True, [])
    emu._apply_engine_startup_config()
    return [call.args[0] for call in emu.engine.command.call_args_list]


def test_configured_startup_values_are_sent_to_the_firmware():
    """The mirror is overwritten by what the firmware reports, so the
    configured level and current only take effect if they are commanded."""
    assert _startup_commands("L1", 16, "L2", 32) == ["$SL 1", "$SC 16"]


def test_startup_values_the_firmware_already_has_are_not_resent():
    assert _startup_commands("L2", 32, "L2", 32) == []


def test_auto_service_level_is_always_sent():
    assert _startup_commands("Auto", 32, "L2", 32) == ["$SL A"]


def test_a_refused_startup_setting_is_reported_not_fatal(capsys):
    from unittest.mock import MagicMock

    emu = make_charging_emulator()
    emu.config["evse"].update(service_level="L1", default_current=16)
    emu.engine = MagicMock()
    emu.engine.service_level = "L2"
    emu.engine.current_capacity = 32
    emu.engine.command.return_value = (False, [])
    emu._apply_engine_startup_config()
    assert "refused startup setting '$SC 16'" in capsys.readouterr().out

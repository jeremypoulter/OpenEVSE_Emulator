"""The web UI's own rules, run in node with the DOM stubbed out.

Only logic that has been kept free of the page is tested here -- which EV
buttons are valid in which state -- because that is where a regression would
hide: the page itself renders whatever it is told.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).parent.parent / "src" / "web" / "static" / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not installed"
)

RUNNER = """
const vm = require('vm');
const fs = require('fs');
const context = vm.createContext({
    io: () => ({ on() {} }),
    document: { addEventListener() {} },
    console,
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const ev = JSON.parse(process.argv[2]);
console.log(JSON.stringify(vm.runInContext('evButtonStates', context)(ev)));
"""


def evaluate(**ev):
    out = subprocess.run(
        ["node", "-e", RUNNER, str(APP_JS), json.dumps(ev)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def buttons(**ev):
    return {name: s["enabled"] for name, s in evaluate(**ev).items()}


def reasons(**ev):
    return {name: s["reason"] for name, s in evaluate(**ev).items()}


def test_unplugged_vehicle_can_only_connect():
    assert buttons(connected=False, requesting_charge=False, soc=50) == {
        "connect": True,
        "disconnect": False,
        "requestCharge": False,
        "stopCharge": False,
    }


def test_connected_idle_vehicle_can_request_or_leave():
    assert buttons(connected=True, requesting_charge=False, soc=50) == {
        "connect": False,
        "disconnect": True,
        "requestCharge": True,
        "stopCharge": False,
    }


def test_requesting_vehicle_can_stop_or_leave():
    assert buttons(connected=True, requesting_charge=True, soc=50) == {
        "connect": False,
        "disconnect": True,
        "requestCharge": False,
        "stopCharge": True,
    }


def test_a_full_battery_cannot_usefully_request_a_charge():
    state = dict(connected=True, requesting_charge=False, soc=80, charge_limit_soc=80)
    assert buttons(**state)["requestCharge"] is False
    assert "charge limit" in reasons(**state)["requestCharge"]


def test_direct_mode_ignores_the_charge_limit():
    state = dict(
        connected=True,
        requesting_charge=False,
        soc=100,
        charge_limit_soc=80,
        direct_mode=True,
    )
    assert buttons(**state)["requestCharge"] is True


def test_a_missing_charge_limit_means_a_full_battery_is_the_limit():
    assert buttons(connected=True, requesting_charge=False, soc=99)["requestCharge"]
    assert not buttons(connected=True, requesting_charge=False, soc=100)[
        "requestCharge"
    ]


def test_every_disabled_button_says_why_and_enabled_ones_do_not():
    for ev in (
        dict(connected=False, requesting_charge=False, soc=50),
        dict(connected=True, requesting_charge=False, soc=50),
        dict(connected=True, requesting_charge=True, soc=50),
    ):
        enabled = buttons(**ev)
        why = reasons(**ev)
        for name, on in enabled.items():
            assert bool(why[name]) == (not on), (ev, name)

"""Heartbeat supervision and the stuck-relay commands ($FH / $FK).

The controller keeps the heartbeat settings across a reboot and trips when no
pulse arrives in time. While $FK runs the controller is busy in its own loop, so
its supervision timer cannot run until the cycle returns. These tests pin that
behaviour so the ESP32 firmware's heartbeat handling can be exercised against it.
"""

import threading
import time

import pytest

from src.emulator.evse import EVSEStateMachine
from src.emulator.ev import EVSimulator
from src.emulator.rapi import RAPIHandler

RECOVERY_SECONDS = 0.3
NEW_FIRMWARE = "9.3.0"
NEW_PROTOCOL = "6.0.0"


def make_handler(firmware=NEW_FIRMWARE, protocol=NEW_PROTOCOL):
    evse = EVSEStateMachine(firmware_version=firmware, protocol_version=protocol)
    handler = RAPIHandler(evse, EVSimulator())
    handler.stuck_recovery_seconds = RECOVERY_SECONDS
    return handler


def _fresh_handler():
    """A handler built with the environment as it is, not the test override."""
    return RAPIHandler(EVSEStateMachine(), EVSimulator())


@pytest.fixture
def rapi():
    return make_handler()


@pytest.fixture
def old_firmware():
    return make_handler(firmware="8.2.3", protocol="5.0.1")


class TestStuckRelayCommands:
    def test_fh_is_refused_before_the_d9_firmware(self, old_firmware):
        assert old_firmware.process_command("$FH").startswith("$NK")

    def test_fk_is_refused_before_the_d9_firmware(self, old_firmware):
        assert old_firmware.process_command("$FK").startswith("$NK")

    def test_fh_is_acknowledged_on_d9(self, rapi):
        assert rapi.process_command("$FH").startswith("$OK")

    def test_fk_is_refused_with_an_ev_connected(self, rapi):
        rapi.ev.connected = True
        start = time.monotonic()
        assert rapi.process_command("$FK").startswith("$NK")
        assert time.monotonic() - start < RECOVERY_SECONDS

    def test_fk_runs_for_the_recovery_duration_then_acknowledges(self, rapi):
        start = time.monotonic()
        response = rapi.process_command("$FK")
        assert response.startswith("$OK")
        assert time.monotonic() - start >= RECOVERY_SECONDS


class TestSupervisionTrip:
    def test_no_pulse_within_the_interval_trips(self, rapi):
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)
        status = rapi.heartbeat_status()
        assert status["missed"] is True
        assert status["trips"] == 1

    def test_a_pulse_in_time_keeps_supervision_quiet(self, rapi):
        rapi.process_command("$SY 1 6")
        for _ in range(4):
            time.sleep(0.4)
            assert rapi.process_command("$SY").startswith("$OK")
        assert rapi.heartbeat_status()["missed"] is False

    def test_disabled_supervision_never_trips(self, rapi):
        rapi.process_command("$SY 0 0")
        time.sleep(0.2)
        assert rapi.heartbeat_status()["missed"] is False

    def test_supervision_does_not_run_while_fk_is_busy(self, rapi):
        rapi.process_command("$SY 1 6")
        rapi.stuck_recovery_seconds = 1.5
        worker = threading.Thread(target=rapi.process_command, args=("$FK",))
        worker.start()
        time.sleep(1.2)  # longer than the interval, but the controller is busy
        assert rapi.heartbeat_status()["missed"] is False
        worker.join()
        # Once $FK returns the timer runs again, and the overdue pulse trips.
        assert rapi.heartbeat_status()["missed"] is True


class TestMissedPulseAcknowledgement:
    def trip(self, rapi):
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)
        assert rapi.heartbeat_status()["missed"] is True

    def test_pulse_while_missed_is_nakd(self, rapi):
        self.trip(rapi)
        assert rapi.process_command("$SY").startswith("$NK")

    def test_nakd_pulses_do_not_restart_the_timer(self, rapi):
        self.trip(rapi)
        rapi.process_command("$SY")
        assert rapi.heartbeat_status()["missed"] is True
        assert rapi.heartbeat_status()["trips"] == 1

    def test_ack_clears_the_trip_and_restarts_supervision(self, rapi):
        self.trip(rapi)
        assert rapi.process_command("$SY 165").startswith("$OK")
        status = rapi.heartbeat_status()
        assert status["missed"] is False
        assert status["acks"] == 1
        # The ack restarts the timer, so an immediate pulse is accepted.
        assert rapi.process_command("$SY").startswith("$OK")


class TestOfferedCurrentFallback:
    def test_trip_drops_offered_current_to_the_limit_and_ack_restores_it(self, rapi):
        rapi.evse.current_capacity_amps = 32
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)
        assert rapi.heartbeat_status()["missed"] is True
        assert rapi.evse.current_capacity_amps == 6

        assert rapi.process_command("$SY 165").startswith("$OK")
        assert rapi.evse.current_capacity_amps == 32

    def test_a_current_command_during_a_trip_survives_the_acknowledgement(self, rapi):
        rapi.evse.current_capacity_amps = 32
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)
        rapi.heartbeat_tick()
        assert rapi.evse.current_capacity_amps == 6

        assert rapi.process_command("$SC 20").startswith("$OK")
        assert rapi.evse.current_capacity_amps == 6  # still limited while tripped

        rapi.process_command("$SY 165")
        assert rapi.evse.current_capacity_amps == 20  # the command, not the old 32

    def test_trip_never_raises_a_lower_offer(self, rapi):
        rapi.evse.current_capacity_amps = 6
        rapi.process_command("$SY 1 10")
        time.sleep(1.1)
        rapi.heartbeat_status()
        assert rapi.evse.current_capacity_amps == 6
        rapi.process_command("$SY 165")
        assert rapi.evse.current_capacity_amps == 6


class TestFkDurationFromEnvironment:
    @pytest.mark.parametrize("raw", ["abc", "nan", "inf"])
    def test_unusable_values_fall_back_to_thirty_seconds(self, monkeypatch, raw):
        monkeypatch.setenv("OPENEVSE_EMU_FK_SECONDS", raw)
        assert _fresh_handler().stuck_recovery_seconds == 30.0

    def test_negative_values_are_clamped_to_zero(self, monkeypatch):
        monkeypatch.setenv("OPENEVSE_EMU_FK_SECONDS", "-5")
        assert _fresh_handler().stuck_recovery_seconds == 0.0


class TestSupervisionWithoutTraffic:
    def test_tick_trips_and_drops_current_with_no_commands_or_status_reads(self, rapi):
        rapi.evse.current_capacity_amps = 32
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)  # the firmware has gone quiet; nothing else calls in
        rapi.heartbeat_tick()
        assert rapi.heartbeat_missed is True
        assert rapi.evse.current_capacity_amps == 6

    def test_tick_does_nothing_while_fk_is_busy(self, rapi):
        rapi.process_command("$SY 1 6")
        rapi.stuck_recovery_seconds = 1.5
        worker = threading.Thread(target=rapi.process_command, args=("$FK",))
        worker.start()
        time.sleep(1.2)
        rapi.heartbeat_tick()
        assert rapi.heartbeat_missed is False
        worker.join()


class TestStatusShowsTheFallbackOnTheTriggeringRead:
    def test_first_status_read_after_a_timeout_reports_the_fallback(self, rapi):
        from src.web.api import WebAPI

        rapi.evse.current_capacity_amps = 32
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)
        api = WebAPI(rapi.evse, rapi.ev, heartbeat_status=rapi.heartbeat_status)
        api.app.config["TESTING"] = True
        with api.app.test_client() as client:
            body = client.get("/api/evse/status").get_json()
        assert body["heartbeat"]["missed"] is True
        assert body["current_capacity"] == 6


class TestCurrentCannotBypassTheTripCap:
    def test_a_32_amp_command_during_a_trip_is_still_capped_until_acknowledged(
        self, rapi
    ):
        rapi.evse.current_capacity_amps = 32
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)
        rapi.heartbeat_tick()
        assert rapi.process_command("$SC 32").startswith("$OK")
        rapi.heartbeat_tick()
        assert rapi.evse.current_capacity_amps == 6
        assert rapi.heartbeat_missed is True

        rapi.process_command("$SY 165")
        assert rapi.evse.current_capacity_amps == 32


class TestPulseTelemetry:
    def test_rejected_pulses_still_count_as_received_traffic(self, rapi):
        rapi.process_command("$SY 1 6")
        time.sleep(1.1)
        rapi.heartbeat_tick()
        time.sleep(0.5)
        assert rapi.process_command("$SY").startswith("$NK")
        status = rapi.heartbeat_status()
        assert status["missed"] is True
        assert status["seconds_since_pulse"] < 0.2

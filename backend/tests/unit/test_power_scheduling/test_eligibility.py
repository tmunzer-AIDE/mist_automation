from datetime import datetime, timezone

from app.modules.power_scheduling.models import PowerSchedule, ScheduleWindow
from app.modules.power_scheduling.services.eligibility import can_disable, compute_expected_status
from app.modules.power_scheduling.state import PowerScheduleState


def _make_schedule(**kwargs) -> PowerSchedule:
    defaults: dict = {
        "site_id": "s1",
        "site_name": "HQ",
        "timezone": "UTC",
        "off_profile_id": "p1",
        "windows": [ScheduleWindow(days=[0, 1, 2, 3, 4], start="22:00", end="06:00")],
        "critical_ap_macs": [],
        "neighbor_rssi_threshold_dbm": -65,
    }
    defaults.update(kwargs)
    return PowerSchedule.model_construct(**defaults)


def _make_state(**kwargs) -> PowerScheduleState:
    s = PowerScheduleState()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


class TestCanDisable:
    def test_empty_ap_no_neighbors_can_disable(self):
        state = _make_state(client_map={}, rf_neighbor_map={"ap1": [("ap2", -70)]})
        schedule = _make_schedule(neighbor_rssi_threshold_dbm=-65)
        # neighbor rssi -70 < -65 threshold, so neighbor is NOT considered close
        assert can_disable("ap1", state, schedule) is True

    def test_ap_with_clients_cannot_disable(self):
        state = _make_state(client_map={"ap1": {"client-mac"}}, rf_neighbor_map={})
        assert can_disable("ap1", state, _make_schedule()) is False

    def test_critical_ap_cannot_disable(self):
        state = _make_state(client_map={}, rf_neighbor_map={})
        schedule = _make_schedule(critical_ap_macs=["ap1"])
        assert can_disable("ap1", state, schedule) is False

    def test_neighbor_with_clients_blocks_disable(self):
        state = _make_state(
            client_map={"ap2": {"client-mac"}},
            rf_neighbor_map={"ap1": [("ap2", -50)]},  # strong signal — within threshold
        )
        schedule = _make_schedule(neighbor_rssi_threshold_dbm=-65)
        assert can_disable("ap1", state, schedule) is False

    def test_neighbor_below_threshold_does_not_block(self):
        state = _make_state(
            client_map={"ap2": {"client-mac"}},
            rf_neighbor_map={"ap1": [("ap2", -80)]},  # weak signal — outside threshold
        )
        schedule = _make_schedule(neighbor_rssi_threshold_dbm=-65)
        assert can_disable("ap1", state, schedule) is True


class TestComputeExpectedStatus:
    def test_inside_window_returns_off_hours(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0, 1, 2, 3, 4, 5, 6], start="22:00", end="06:00")],
        )
        # Monday 23:00 UTC — inside window
        now = datetime(2026, 3, 30, 23, 0, tzinfo=timezone.utc)  # Monday
        assert compute_expected_status(schedule, now) == "OFF_HOURS"

    def test_outside_window_returns_idle(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0, 1, 2, 3, 4, 5, 6], start="22:00", end="06:00")],
        )
        # Monday 14:00 UTC — outside window
        now = datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc)
        assert compute_expected_status(schedule, now) == "IDLE"

    def test_after_midnight_inside_window(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0, 1, 2, 3, 4, 5, 6], start="22:00", end="06:00")],
        )
        # Tuesday 02:00 UTC — inside the Mon→Tue crossing window
        now = datetime(2026, 3, 31, 2, 0, tzinfo=timezone.utc)
        assert compute_expected_status(schedule, now) == "OFF_HOURS"

    def test_wrong_day_returns_idle(self):
        schedule = _make_schedule(
            timezone="UTC",
            windows=[ScheduleWindow(days=[0, 1, 2, 3, 4], start="22:00", end="06:00")],  # weekdays
        )
        # Saturday 23:00 UTC
        now = datetime(2026, 4, 4, 23, 0, tzinfo=timezone.utc)  # Saturday
        assert compute_expected_status(schedule, now) == "IDLE"

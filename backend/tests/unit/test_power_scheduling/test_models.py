import pytest
from pydantic import ValidationError
from app.modules.power_scheduling.models import PowerSchedule, PowerScheduleLog, ScheduleWindow


class TestScheduleWindow:
    def test_valid_window(self):
        w = ScheduleWindow(days=[0, 1, 2, 3, 4], start="22:00", end="06:00")
        assert w.days == [0, 1, 2, 3, 4]
        assert w.start == "22:00"

    def test_invalid_day(self):
        with pytest.raises(ValidationError):
            ScheduleWindow(days=[7], start="22:00", end="06:00")

    def test_invalid_time_format(self):
        with pytest.raises(ValidationError):
            ScheduleWindow(days=[0], start="10pm", end="06:00")


class TestPowerSchedule:
    def test_defaults(self):
        s = PowerSchedule.model_construct(
            site_id="abc", site_name="HQ", timezone="America/New_York",
            windows=[ScheduleWindow(days=[0, 1, 2, 3, 4], start="22:00", end="06:00")],
            off_profile_id="prof-123",
        )
        assert s.neighbor_rssi_threshold_dbm == -65
        assert s.grace_period_minutes == 5
        assert s.roam_rssi_threshold_dbm == -75
        assert s.enabled is True
        assert s.current_status == "IDLE"
        assert s.critical_ap_macs == []

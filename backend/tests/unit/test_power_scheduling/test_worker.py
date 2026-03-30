from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.power_scheduling.models import PowerSchedule, ScheduleWindow
from app.modules.power_scheduling.workers.schedule_worker import (
    deregister_schedule_jobs,
    register_schedule_jobs,
    run_startup_recovery,
)


def _make_schedule(site_id="s1", current_status="IDLE", timezone="UTC"):
    return PowerSchedule.model_construct(
        id="507f1f77bcf86cd799439011",
        site_id=site_id,
        site_name="HQ",
        timezone=timezone,
        off_profile_id="p1",
        windows=[ScheduleWindow(days=list(range(7)), start="22:00", end="06:00")],
        current_status=current_status,
        last_transition_at=None,
        enabled=True,
    )


class TestRegisterJobs:
    def test_adds_two_jobs_per_window(self):
        mock_scheduler = MagicMock()
        schedule = _make_schedule()
        register_schedule_jobs(schedule, mock_scheduler)
        # 1 window × 2 jobs (off + on)
        assert mock_scheduler.add_job.call_count == 2

    def test_job_ids_are_namespaced(self):
        mock_scheduler = MagicMock()
        register_schedule_jobs(_make_schedule(site_id="xyz"), mock_scheduler)
        job_ids = [c.kwargs["id"] for c in mock_scheduler.add_job.call_args_list]
        assert all("xyz" in jid for jid in job_ids)

    def test_deregister_removes_jobs(self):
        mock_scheduler = MagicMock()
        mock_scheduler.get_job.return_value = MagicMock()
        deregister_schedule_jobs("s1", mock_scheduler)
        mock_scheduler.remove_job.assert_called()


class TestStartupRecovery:
    async def test_missed_off_triggers_start(self):
        schedule = _make_schedule(current_status="IDLE")
        # now is inside the window (23:00 UTC Monday, March 30 2026 is a Monday)
        now = datetime(2026, 3, 30, 23, 0, tzinfo=timezone.utc)
        with (
            patch(
                "app.modules.power_scheduling.workers.schedule_worker.start_off_hours",
                new_callable=AsyncMock,
            ) as mock_start,
            patch(
                "app.modules.power_scheduling.workers.schedule_worker.end_off_hours_catchup",
                new_callable=AsyncMock,
            ),
        ):
            await run_startup_recovery(schedule, now)
        mock_start.assert_awaited_once()

    async def test_missed_on_triggers_catchup(self):
        schedule = _make_schedule(current_status="OFF_HOURS")
        # now is outside window (14:00 UTC)
        now = datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc)
        with (
            patch(
                "app.modules.power_scheduling.workers.schedule_worker.start_off_hours",
                new_callable=AsyncMock,
            ),
            patch(
                "app.modules.power_scheduling.workers.schedule_worker.end_off_hours_catchup",
                new_callable=AsyncMock,
            ) as mock_catchup,
        ):
            await run_startup_recovery(schedule, now)
        mock_catchup.assert_awaited_once()

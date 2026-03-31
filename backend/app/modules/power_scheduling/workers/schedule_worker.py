from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytz
import structlog
from apscheduler.triggers.cron import CronTrigger

from app.modules.power_scheduling.models import PowerSchedule
from app.modules.power_scheduling.services.eligibility import compute_expected_status
from app.modules.power_scheduling.services.scheduling_service import (
    end_off_hours,
    end_off_hours_catchup,
    on_client_event,
    start_off_hours,
)

log = structlog.get_logger(__name__).bind(module="power_scheduling")

# Module-level reference to the ClientStatsWsManager (set during app startup)
_client_ws_manager = None


def get_client_ws_manager():
    return _client_ws_manager


def register_schedule_jobs(schedule: PowerSchedule, scheduler) -> None:
    """Register APScheduler on/off cron jobs for a schedule."""
    tz = pytz.timezone(schedule.timezone)
    for i, window in enumerate(schedule.windows):
        off_h, off_m = map(int, window.start.split(":"))
        on_h, on_m = map(int, window.end.split(":"))
        days_str = ",".join(str(d) for d in window.days)

        scheduler.add_job(
            _start_off_hours_job,
            trigger=CronTrigger(day_of_week=days_str, hour=off_h, minute=off_m, timezone=tz),
            id=f"ps_off_{schedule.site_id}_{i}",
            kwargs={"site_id": schedule.site_id},
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        scheduler.add_job(
            _end_off_hours_job,
            trigger=CronTrigger(day_of_week=days_str, hour=on_h, minute=on_m, timezone=tz),
            id=f"ps_on_{schedule.site_id}_{i}",
            kwargs={"site_id": schedule.site_id},
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    log.info("schedule_jobs_registered", site_id=schedule.site_id, windows=len(schedule.windows))


def deregister_schedule_jobs(site_id: str, scheduler, window_count: int) -> None:
    """Remove all APScheduler jobs for a site."""
    for i in range(window_count):
        for direction in ("off", "on"):
            job_id = f"ps_{direction}_{site_id}_{i}"
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)


async def _start_off_hours_job(site_id: str) -> None:
    schedule = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if schedule and schedule.enabled:
        await start_off_hours(schedule)


async def _end_off_hours_job(site_id: str) -> None:
    schedule = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if schedule and schedule.enabled:
        await end_off_hours(schedule)


async def run_startup_recovery(schedule: PowerSchedule, now: datetime | None = None) -> None:
    """Detect missed transitions and catch up."""
    if now is None:
        now = datetime.now(timezone.utc)
    expected = compute_expected_status(schedule, now)
    site_id = schedule.site_id

    if expected == "OFF_HOURS" and schedule.current_status == "IDLE":
        log.info("catchup_start_off", site_id=site_id)
        await start_off_hours(schedule)
    elif expected == "IDLE" and schedule.current_status == "OFF_HOURS":
        log.info("catchup_start_on", site_id=site_id)
        await end_off_hours_catchup(schedule)


async def startup_power_scheduling(api_session) -> None:
    """
    Called from app lifespan. Registers all enabled schedule jobs,
    starts client WS subscriptions, and runs startup recovery.
    """
    global _client_ws_manager

    from app.core.tasks import create_background_task
    from app.modules.power_scheduling.services.client_ws_service import ClientStatsWsManager
    from app.workers import get_scheduler

    schedules = await PowerSchedule.find(PowerSchedule.enabled == True).to_list()  # noqa: E712

    loop = asyncio.get_running_loop()

    def _client_event_bridge(site_id: str, event_type: str, client_mac: str, ap_mac: str, rssi: int | None) -> None:

        async def _dispatch() -> None:
            sched = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
            if sched:
                await on_client_event(site_id, event_type, client_mac, ap_mac, rssi, sched)

        loop.call_soon_threadsafe(lambda: create_background_task(_dispatch(), name=f"ps-event-{site_id}"))

    _client_ws_manager = ClientStatsWsManager(api_session=api_session, on_event=_client_event_bridge)

    if not schedules:
        return

    scheduler = get_scheduler().scheduler
    site_ids = [s.site_id for s in schedules]

    await _client_ws_manager.start(site_ids)

    for schedule in schedules:
        register_schedule_jobs(schedule, scheduler)

    for schedule in schedules:
        await run_startup_recovery(schedule)

    log.info("power_scheduling_started", sites=len(schedules))

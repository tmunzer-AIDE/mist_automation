from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.dependencies import require_impact_role
from app.models.user import User
from app.modules.power_scheduling.models import PowerSchedule, PowerScheduleLog, ScheduleWindow
from app.modules.power_scheduling.services.scheduling_service import (
    end_off_hours,
    end_off_hours_catchup,
    start_off_hours,
)
from app.modules.power_scheduling.state import get_state
from app.services.mist_service_factory import create_mist_service

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Power Scheduling"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ScheduleWindowSchema(BaseModel):
    days: list[int]
    start: str
    end: str


class CreateScheduleRequest(BaseModel):
    site_id: str
    site_name: str
    windows: list[ScheduleWindowSchema]
    grace_period_minutes: int = 5
    neighbor_rssi_threshold_dbm: int = -65
    roam_rssi_threshold_dbm: int = -75
    critical_ap_macs: list[str] = []
    enabled: bool = True


class ScheduleResponse(BaseModel):
    id: str
    site_id: str
    site_name: str
    timezone: str
    windows: list[ScheduleWindowSchema]
    off_profile_id: str
    grace_period_minutes: int
    neighbor_rssi_threshold_dbm: int
    roam_rssi_threshold_dbm: int
    critical_ap_macs: list[str]
    enabled: bool
    current_status: str


class ScheduleStatusResponse(BaseModel):
    site_id: str
    status: str
    disabled_ap_count: int
    pending_disable_count: int
    client_ap_count: int


class TriggerRequest(BaseModel):
    action: str  # "start" | "end"


class LogResponse(BaseModel):
    id: str
    site_id: str
    timestamp: str
    event_type: str
    ap_mac: str | None
    details: dict


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


async def _fetch_site_timezone(site_id: str) -> str:
    mist = await create_mist_service()
    data = await mist.api_get(f"/api/v1/sites/{site_id}")
    return data.get("timezone", "UTC")


async def _setup_mist_profile(site_id: str) -> str:
    """Create the power-schedule-off device profile in Mist and return its ID."""
    mist = await create_mist_service()
    body: dict[str, Any] = {
        "name": f"power-schedule-off-{site_id}",
        "radio_config": {
            "band_24": {"disabled": True},
            "band_5": {"disabled": True},
            "band_6": {"disabled": True},
        },
    }
    result = await mist.api_post(f"/api/v1/sites/{site_id}/deviceprofiles", body)
    return result["id"]


def _register_jobs(schedule: PowerSchedule) -> None:
    from app.modules.power_scheduling.workers.schedule_worker import register_schedule_jobs
    from app.workers import get_scheduler

    register_schedule_jobs(schedule, get_scheduler().scheduler)


def _deregister_jobs(site_id: str) -> None:
    from app.modules.power_scheduling.workers.schedule_worker import deregister_schedule_jobs
    from app.workers import get_scheduler

    deregister_schedule_jobs(site_id, get_scheduler().scheduler)


def _schedule_to_response(s: PowerSchedule) -> ScheduleResponse:
    return ScheduleResponse(
        id=str(s.id),
        site_id=s.site_id,
        site_name=s.site_name,
        timezone=s.timezone,
        windows=[ScheduleWindowSchema(**w.model_dump()) for w in s.windows],
        off_profile_id=s.off_profile_id,
        grace_period_minutes=s.grace_period_minutes,
        neighbor_rssi_threshold_dbm=s.neighbor_rssi_threshold_dbm,
        roam_rssi_threshold_dbm=s.roam_rssi_threshold_dbm,
        critical_ap_macs=s.critical_ap_macs,
        enabled=s.enabled,
        current_status=s.current_status,
    )


async def _get_schedule_or_404(site_id: str) -> PowerSchedule:
    s = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return s


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/power-scheduling/sites", response_model=list[ScheduleResponse])
async def list_schedules(_: User = Depends(require_impact_role)) -> list[ScheduleResponse]:
    schedules = await PowerSchedule.find_all().to_list()
    return [_schedule_to_response(s) for s in schedules]


@router.post(
    "/power-scheduling/sites/{site_id}",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    site_id: str,
    body: CreateScheduleRequest,
    _: User = Depends(require_impact_role),
) -> ScheduleResponse:
    existing = await PowerSchedule.find_one(PowerSchedule.site_id == site_id)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Schedule already exists for this site")

    timezone_str = await _fetch_site_timezone(site_id)
    off_profile_id = await _setup_mist_profile(site_id)

    schedule = PowerSchedule(
        site_id=site_id,
        site_name=body.site_name,
        timezone=timezone_str,
        windows=[ScheduleWindow(**w.model_dump()) for w in body.windows],
        off_profile_id=off_profile_id,
        grace_period_minutes=body.grace_period_minutes,
        neighbor_rssi_threshold_dbm=body.neighbor_rssi_threshold_dbm,
        roam_rssi_threshold_dbm=body.roam_rssi_threshold_dbm,
        critical_ap_macs=body.critical_ap_macs,
        enabled=body.enabled,
    )
    await schedule.insert()

    if schedule.enabled:
        _register_jobs(schedule)
        from app.modules.power_scheduling.workers.schedule_worker import get_client_ws_manager

        ws = get_client_ws_manager()
        if ws:
            await ws.add_site(site_id)

    log.info("schedule_created", site_id=site_id)
    return _schedule_to_response(schedule)


@router.put("/power-scheduling/sites/{site_id}", response_model=ScheduleResponse)
async def update_schedule(
    site_id: str,
    body: CreateScheduleRequest,
    _: User = Depends(require_impact_role),
) -> ScheduleResponse:
    schedule = await _get_schedule_or_404(site_id)
    _deregister_jobs(site_id)

    schedule.windows = [ScheduleWindow(**w.model_dump()) for w in body.windows]
    schedule.grace_period_minutes = body.grace_period_minutes
    schedule.neighbor_rssi_threshold_dbm = body.neighbor_rssi_threshold_dbm
    schedule.roam_rssi_threshold_dbm = body.roam_rssi_threshold_dbm
    schedule.critical_ap_macs = body.critical_ap_macs
    schedule.enabled = body.enabled
    schedule.update_timestamp()
    await schedule.save()

    if schedule.enabled:
        _register_jobs(schedule)

    return _schedule_to_response(schedule)


@router.delete("/power-scheduling/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    site_id: str,
    _: User = Depends(require_impact_role),
) -> None:
    schedule = await _get_schedule_or_404(site_id)
    _deregister_jobs(site_id)

    if schedule.current_status == "OFF_HOURS":
        await end_off_hours_catchup(schedule)

    try:
        mist = await create_mist_service()
        await mist.api_delete(f"/api/v1/sites/{site_id}/deviceprofiles/{schedule.off_profile_id}")
    except Exception as exc:
        log.warning("profile_delete_failed", site_id=site_id, error=str(exc))

    from app.modules.power_scheduling.workers.schedule_worker import get_client_ws_manager

    ws = get_client_ws_manager()
    if ws:
        await ws.remove_site(site_id)

    from app.modules.power_scheduling.state import clear_state

    await clear_state(site_id)
    await schedule.delete()


@router.get("/power-scheduling/sites/{site_id}/status", response_model=ScheduleStatusResponse)
async def get_status(
    site_id: str,
    _: User = Depends(require_impact_role),
) -> ScheduleStatusResponse:
    await _get_schedule_or_404(site_id)
    state = get_state(site_id)
    return ScheduleStatusResponse(
        site_id=site_id,
        status=state.status,
        disabled_ap_count=len(state.disabled_aps),
        pending_disable_count=len(state.pending_disable),
        client_ap_count=len(state.client_map),
    )


@router.get("/power-scheduling/sites/{site_id}/logs", response_model=list[LogResponse])
async def get_logs(
    site_id: str,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    event_type: str | None = Query(None),
    _: User = Depends(require_impact_role),
) -> list[LogResponse]:
    await _get_schedule_or_404(site_id)
    query = PowerScheduleLog.find(PowerScheduleLog.site_id == site_id)
    if event_type:
        query = query.find(PowerScheduleLog.event_type == event_type)
    logs = await query.sort(-PowerScheduleLog.timestamp).skip(skip).limit(limit).to_list()
    return [
        LogResponse(
            id=str(lg.id),
            site_id=lg.site_id,
            timestamp=lg.timestamp.isoformat(),
            event_type=lg.event_type,
            ap_mac=lg.ap_mac,
            details=lg.details,
        )
        for lg in logs
    ]


@router.post("/power-scheduling/sites/{site_id}/trigger")
async def manual_trigger(
    site_id: str,
    body: TriggerRequest,
    _: User = Depends(require_impact_role),
) -> dict[str, str]:
    schedule = await _get_schedule_or_404(site_id)
    if body.action == "start":
        from app.core.tasks import create_background_task

        create_background_task(start_off_hours(schedule), name=f"ps-manual-start-{site_id}")
        return {"status": "triggered", "action": "start"}
    elif body.action == "end":
        from app.core.tasks import create_background_task

        create_background_task(end_off_hours(schedule), name=f"ps-manual-end-{site_id}")
        return {"status": "triggered", "action": "end"}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="action must be 'start' or 'end'")

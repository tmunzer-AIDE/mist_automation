from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.tasks import create_background_task
from app.modules.power_scheduling.models import PowerSchedule, PowerScheduleLog
from app.modules.power_scheduling.services.eligibility import can_disable
from app.modules.power_scheduling.services.rrm_service import fetch_rf_neighbor_map
from app.modules.power_scheduling.state import PowerScheduleState, get_lock, get_state
from app.services.mist_service_factory import create_mist_service

log = structlog.get_logger(__name__).bind(module="power_scheduling")


# ---------------------------------------------------------------------------
# Mist API helpers
# ---------------------------------------------------------------------------


async def _get_ap_inventory(site_id: str) -> list[dict[str, Any]]:
    """Return list of AP dicts with at least 'mac' and 'deviceprofile_id'."""
    mist = await create_mist_service()
    data = await mist.api_get(f"/api/v1/sites/{site_id}/devices?type=ap")
    return data if isinstance(data, list) else []


async def _assign_profile(site_id: str, ap_mac: str, profile_id: str | None) -> None:
    """Set or clear the device profile on an AP."""
    mist = await create_mist_service()
    body: dict[str, Any] = {"deviceprofile_id": profile_id}
    await mist.api_put(f"/api/v1/sites/{site_id}/devices/{ap_mac}", body)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


async def _log_event(
    site_id: str,
    event_type: str,
    ap_mac: str | None = None,
    **details: Any,
) -> None:
    entry = PowerScheduleLog(site_id=site_id, event_type=event_type, ap_mac=ap_mac, details=details)
    await entry.insert()
    log.info(event_type.lower(), site_id=site_id, ap_mac=ap_mac, **details)


# ---------------------------------------------------------------------------
# Main transitions
# ---------------------------------------------------------------------------


async def start_off_hours(schedule: PowerSchedule) -> None:
    """TRANSITIONING_OFF → OFF_HOURS: disable eligible APs, add rest to pending."""
    site_id = schedule.site_id
    state = get_state(site_id)

    async with get_lock(site_id):
        state.status = "TRANSITIONING_OFF"

    await _log_event(site_id, "WINDOW_START")

    rf_map = await fetch_rf_neighbor_map(site_id)
    ap_inventory = await _get_ap_inventory(site_id)

    async with get_lock(site_id):
        state.rf_neighbor_map = rf_map
        state.pending_disable.clear()
        state.disabled_aps.clear()

    for ap in ap_inventory:
        ap_mac: str = ap["mac"]
        original_profile: str | None = ap.get("deviceprofile_id")

        async with get_lock(site_id):
            eligible = can_disable(ap_mac, state, schedule)

        if eligible:
            try:
                await _assign_profile(site_id, ap_mac, schedule.off_profile_id)
                async with get_lock(site_id):
                    state.disabled_aps[ap_mac] = original_profile
                await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, original_profile=original_profile)
            except Exception as exc:
                await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="disable")
        else:
            async with get_lock(site_id):
                state.pending_disable.add(ap_mac)
                reason = "has_clients" if state.client_map.get(ap_mac) else "neighbor_has_clients"
            await _log_event(site_id, "AP_PENDING", ap_mac=ap_mac, reason=reason)

    async with get_lock(site_id):
        state.status = "OFF_HOURS"

    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {"$set": {"current_status": "OFF_HOURS", "last_transition_at": datetime.now(timezone.utc)}}
    )


async def end_off_hours(schedule: PowerSchedule) -> None:
    """TRANSITIONING_ON → IDLE: restore all disabled APs."""
    site_id = schedule.site_id
    state = get_state(site_id)

    async with get_lock(site_id):
        state.status = "TRANSITIONING_ON"
        disabled = dict(state.disabled_aps)
        tasks_to_cancel = list(state.grace_tasks.values())
        for task in tasks_to_cancel:
            task.cancel()
        state.grace_tasks.clear()
        state.pending_disable.clear()

    await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    for ap_mac, original_profile in disabled.items():
        try:
            await _assign_profile(site_id, ap_mac, original_profile)
            await _log_event(
                site_id, "AP_ENABLED", ap_mac=ap_mac, reason="window_end", original_profile=original_profile
            )
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="re-enable")

    async with get_lock(site_id):
        state.disabled_aps.clear()
        state.status = "IDLE"

    await _log_event(site_id, "WINDOW_END")
    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {"$set": {"current_status": "IDLE", "last_transition_at": datetime.now(timezone.utc)}}
    )


async def end_off_hours_catchup(schedule: PowerSchedule) -> None:
    """Startup recovery: query Mist API for APs with off_profile_id and restore them."""
    site_id = schedule.site_id
    await _log_event(site_id, "CATCHUP_START", direction="on")

    ap_inventory = await _get_ap_inventory(site_id)
    for ap in ap_inventory:
        if ap.get("deviceprofile_id") == schedule.off_profile_id:
            try:
                await _assign_profile(site_id, ap["mac"], None)
                await _log_event(site_id, "AP_ENABLED", ap_mac=ap["mac"], reason="catchup")
            except Exception as exc:
                await _log_event(site_id, "ERROR", ap_mac=ap["mac"], error=str(exc), action="catchup_re-enable")

    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {"$set": {"current_status": "IDLE", "last_transition_at": datetime.now(timezone.utc)}}
    )
    await _log_event(site_id, "CATCHUP_END", direction="on")


# ---------------------------------------------------------------------------
# OFF_HOURS event handlers
# ---------------------------------------------------------------------------


async def on_client_event(
    site_id: str,
    event_type: str,
    client_mac: str,
    ap_mac: str,
    rssi: int | None,
    schedule: PowerSchedule,
) -> None:
    """Handle client WS events during OFF_HOURS."""
    state = get_state(site_id)

    async with get_lock(site_id):
        if state.status != "OFF_HOURS":
            return

    if event_type == "join":
        await _handle_client_join(site_id, ap_mac, client_mac, state, schedule)
    elif event_type == "leave":
        await _handle_client_leave(site_id, ap_mac, client_mac, state, schedule)
    elif event_type == "update" and rssi is not None:
        await _handle_rssi_update(site_id, ap_mac, client_mac, rssi, state, schedule)


async def _handle_client_join(
    site_id: str,
    ap_mac: str,
    client_mac: str,
    state: PowerScheduleState,
    schedule: PowerSchedule,
) -> None:
    async with get_lock(site_id):
        state.client_map.setdefault(ap_mac, set()).add(client_mac)
        if ap_mac in state.grace_tasks:
            state.grace_tasks.pop(ap_mac).cancel()

    await _log_event(site_id, "CLIENT_DETECTED", ap_mac=ap_mac, client_mac=client_mac)

    async with get_lock(site_id):
        was_disabled = ap_mac in state.disabled_aps
        original = state.disabled_aps.pop(ap_mac, None)

    if was_disabled:
        try:
            await _assign_profile(site_id, ap_mac, original)
            await _log_event(site_id, "AP_ENABLED", ap_mac=ap_mac, reason="client_arrived", client_mac=client_mac)
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="re-enable_on_client")

    async with get_lock(site_id):
        neighbors = state.rf_neighbor_map.get(ap_mac, [])
        to_enable = [
            (nbr_mac, state.disabled_aps.pop(nbr_mac, None))
            for nbr_mac, rssi in neighbors
            if rssi > schedule.neighbor_rssi_threshold_dbm and nbr_mac in state.disabled_aps
        ]

    for nbr_mac, orig_prof in to_enable:
        try:
            await _assign_profile(site_id, nbr_mac, orig_prof)
            await _log_event(site_id, "AP_ENABLED", ap_mac=nbr_mac, reason="neighbor_coverage", triggering_ap=ap_mac)
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=nbr_mac, error=str(exc), action="re-enable_neighbor")

    await _reevaluate_pending(site_id, state, schedule)


async def _handle_client_leave(
    site_id: str,
    ap_mac: str,
    client_mac: str,
    state: PowerScheduleState,
    schedule: PowerSchedule,
) -> None:
    async with get_lock(site_id):
        ap_clients = state.client_map.get(ap_mac, set())
        ap_clients.discard(client_mac)
        if not ap_clients:
            state.client_map.pop(ap_mac, None)
        is_now_empty = not bool(ap_clients)

    await _log_event(site_id, "CLIENT_LEFT", ap_mac=ap_mac, client_mac=client_mac)

    if is_now_empty and ap_mac in state.pending_disable:
        await _log_event(site_id, "GRACE_TIMER_START", ap_mac=ap_mac, grace_minutes=schedule.grace_period_minutes)
        task = create_background_task(
            _grace_timer(site_id, ap_mac, schedule),
            name=f"grace-{site_id}-{ap_mac}",
        )
        async with get_lock(site_id):
            state.grace_tasks[ap_mac] = task

    await _reevaluate_pending(site_id, state, schedule)


async def _grace_timer(site_id: str, ap_mac: str, schedule: PowerSchedule) -> None:
    """Wait grace period, then disable AP if still empty and eligible."""
    await asyncio.sleep(schedule.grace_period_minutes * 60)
    state = get_state(site_id)
    async with get_lock(site_id):
        state.grace_tasks.pop(ap_mac, None)
        if ap_mac not in state.pending_disable:
            return
        if not can_disable(ap_mac, state, schedule):
            return

    try:
        mist = await create_mist_service()
        ap_data = await mist.api_get(f"/api/v1/sites/{site_id}/devices/{ap_mac}")
        original = ap_data.get("deviceprofile_id")
        await _assign_profile(site_id, ap_mac, schedule.off_profile_id)
        async with get_lock(site_id):
            state.pending_disable.discard(ap_mac)
            state.disabled_aps[ap_mac] = original
        await _log_event(site_id, "GRACE_TIMER_EXPIRED", ap_mac=ap_mac)
        await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, reason="grace_expired", original_profile=original)
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=str(exc), action="grace_disable")


async def _handle_rssi_update(
    site_id: str,
    ap_mac: str,
    client_mac: str,
    rssi: int,
    state: PowerScheduleState,
    schedule: PowerSchedule,
) -> None:
    """Pre-enable disabled neighbors when client RSSI is degrading."""
    if rssi >= schedule.roam_rssi_threshold_dbm:
        return

    async with get_lock(site_id):
        neighbors = state.rf_neighbor_map.get(ap_mac, [])
        to_enable = [
            (nbr_mac, state.disabled_aps.pop(nbr_mac, None))
            for nbr_mac, nbr_rssi in neighbors
            if nbr_rssi > schedule.neighbor_rssi_threshold_dbm and nbr_mac in state.disabled_aps
        ]

    for nbr_mac, orig_prof in to_enable:
        try:
            await _assign_profile(site_id, nbr_mac, orig_prof)
            await _log_event(
                site_id,
                "AP_ENABLED",
                ap_mac=nbr_mac,
                reason="rssi_pre_enable",
                client_mac=client_mac,
                current_ap=ap_mac,
                rssi=rssi,
            )
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=nbr_mac, error=str(exc), action="rssi_pre_enable")


async def _reevaluate_pending(site_id: str, state: PowerScheduleState, schedule: PowerSchedule) -> None:
    """Check if any pending_disable AP is now eligible after a client_map change."""
    async with get_lock(site_id):
        now_eligible = [
            ap for ap in state.pending_disable if can_disable(ap, state, schedule) and ap not in state.grace_tasks
        ]

    for ap_mac in now_eligible:
        await _log_event(site_id, "GRACE_TIMER_START", ap_mac=ap_mac, grace_minutes=schedule.grace_period_minutes)
        task = create_background_task(
            _grace_timer(site_id, ap_mac, schedule),
            name=f"grace-{site_id}-{ap_mac}",
        )
        async with get_lock(site_id):
            if ap_mac not in state.grace_tasks:  # double-check under lock
                state.grace_tasks[ap_mac] = task
            else:
                task.cancel()

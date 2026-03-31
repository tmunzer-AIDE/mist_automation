from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.tasks import create_background_task
from app.core.websocket import ws_manager
from app.modules.power_scheduling.models import PowerSchedule, PowerScheduleLog
from app.modules.power_scheduling.services.eligibility import can_disable
from app.modules.power_scheduling.services.rrm_service import fetch_rf_neighbor_map
from app.modules.power_scheduling.state import PowerScheduleState, get_lock, get_state
from app.services.mist_service_factory import create_mist_service

log = structlog.get_logger(__name__).bind(module="power_scheduling")

# ---------------------------------------------------------------------------
# Radio override payloads
# ---------------------------------------------------------------------------

_RADIO_OVERRIDE_ON: dict[str, Any] = {
    "radio_config": {
        "band_24": {"disabled": False, "allow_rrm_disable": False, "channel": 0},
        "band_5": {"disabled": False, "allow_rrm_disable": False, "channel": 0},
    }
}

_PROFILE_RADIOS_OFF: dict[str, Any] = {
    "radio_config": {
        "band_24": {"disabled": True},
        "band_5": {"disabled": True},
        "band_6": {"disabled": True},
    }
}

# ---------------------------------------------------------------------------
# Mist API helpers
# ---------------------------------------------------------------------------


async def _get_ap_inventory(site_id: str) -> list[dict[str, Any]]:
    """Return list of AP dicts with at least 'mac'."""
    mist = await create_mist_service()
    data = await mist.api_get(f"/api/v1/sites/{site_id}/devices?type=ap")
    return data if isinstance(data, list) else []


async def _set_ap_override(site_id: str, ap_mac: str) -> None:
    """Set per-AP radio override to keep radios enabled."""
    mist = await create_mist_service()
    await mist.api_put(f"/api/v1/sites/{site_id}/devices/{ap_mac}", _RADIO_OVERRIDE_ON)


async def _clear_ap_override(site_id: str, ap_mac: str) -> None:
    """Remove per-AP radio override (AP falls back to device profile)."""
    mist = await create_mist_service()
    await mist.api_put(f"/api/v1/sites/{site_id}/devices/{ap_mac}", {"radio_config": {}})


async def _batch_set_ap_overrides(site_id: str, macs: list[str]) -> None:
    """Set radio override on multiple APs in parallel."""
    results = await asyncio.gather(*[_set_ap_override(site_id, m) for m in macs], return_exceptions=True)
    for mac, result in zip(macs, results):
        if isinstance(result, Exception):
            log.warning("batch_set_override_failed", site_id=site_id, mac=mac, error=str(result))


async def _batch_clear_ap_overrides(site_id: str, macs: list[str]) -> None:
    """Clear radio override on multiple APs in parallel."""
    results = await asyncio.gather(*[_clear_ap_override(site_id, m) for m in macs], return_exceptions=True)
    for mac, result in zip(macs, results):
        if isinstance(result, Exception):
            log.warning("batch_clear_override_failed", site_id=site_id, mac=mac, error=str(result))


async def _update_profile_radio(profile_id: str, radio_config: dict[str, Any]) -> None:
    """Update device profile radio config (pass {} to restore neutral state)."""
    mist = await create_mist_service()
    await mist.api_put(
        f"/api/v1/orgs/{mist.org_id}/deviceprofiles/{profile_id}",
        {"radio_config": radio_config},
    )


# ---------------------------------------------------------------------------
# WebSocket broadcasting
# ---------------------------------------------------------------------------


async def _broadcast_status(site_id: str, current_status: str) -> None:
    """Broadcast current in-memory state to any connected frontend subscribers."""
    state = get_state(site_id)
    await ws_manager.broadcast(
        f"power_scheduling:{site_id}",
        {
            "type": "status_update",
            "data": {
                "status": state.status,
                "current_status": current_status,
                "disabled_ap_count": max(0, state.total_non_critical_aps - len(state.protected_aps)),
                "pending_disable_count": len(state.protected_aps),
                "client_ap_count": len(state.client_map),
            },
        },
    )


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
    await ws_manager.broadcast(
        f"power_scheduling:{site_id}",
        {
            "type": "log_entry",
            "data": {
                "id": str(entry.id),
                "site_id": site_id,
                "timestamp": entry.timestamp.isoformat(),
                "event_type": event_type,
                "ap_mac": ap_mac,
                "details": details,
            },
        },
    )


# ---------------------------------------------------------------------------
# Main transitions
# ---------------------------------------------------------------------------


async def start_off_hours(schedule: PowerSchedule) -> None:
    """TRANSITIONING_OFF → OFF_HOURS: protect exception APs, then disable via profile."""
    site_id = schedule.site_id
    state = get_state(site_id)

    async with get_lock(site_id):
        state.status = "TRANSITIONING_OFF"

    await _log_event(site_id, "WINDOW_START")

    rf_map = await fetch_rf_neighbor_map(site_id)
    ap_inventory = await _get_ap_inventory(site_id)

    async with get_lock(site_id):
        state.rf_neighbor_map = rf_map

    # Classify APs: those that need protection vs those the profile can disable
    to_protect: list[str] = []
    to_disable: list[str] = []

    for ap in ap_inventory:
        ap_mac: str = ap["mac"]
        if ap_mac in schedule.critical_ap_macs:
            continue  # Never touch critical APs
        async with get_lock(site_id):
            eligible = can_disable(ap_mac, state, schedule)
        if eligible:
            to_disable.append(ap_mac)
        else:
            to_protect.append(ap_mac)

    # Step 1: add AP-level overrides for exception APs (keep radios on)
    if to_protect:
        try:
            await _batch_set_ap_overrides(site_id, to_protect)
            for ap_mac in to_protect:
                await _log_event(site_id, "AP_PENDING", ap_mac=ap_mac, reason="has_clients_or_neighbor")
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=None, error=type(exc).__name__, action="batch_protect")

    # Step 2: update profile to disable radios for everyone else
    try:
        await _update_profile_radio(schedule.off_profile_id, _PROFILE_RADIOS_OFF["radio_config"])
        for ap_mac in to_disable:
            await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, reason="profile_updated")
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=None, error=type(exc).__name__, action="profile_disable")

    async with get_lock(site_id):
        state.protected_aps = set(to_protect)
        state.total_non_critical_aps = len(to_protect) + len(to_disable)
        state.status = "OFF_HOURS"

    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {
            "$set": {
                "current_status": "OFF_HOURS",
                "protected_ap_macs": to_protect,
                "last_transition_at": datetime.now(timezone.utc),
            }
        }
    )
    await _broadcast_status(site_id, "OFF_HOURS")


async def end_off_hours(schedule: PowerSchedule) -> None:
    """TRANSITIONING_ON → IDLE: remove AP overrides, restore profile to neutral."""
    site_id = schedule.site_id
    state = get_state(site_id)

    async with get_lock(site_id):
        state.status = "TRANSITIONING_ON"
        protected = set(state.protected_aps)
        tasks_to_cancel = list(state.grace_tasks.values())
        for task in tasks_to_cancel:
            task.cancel()
        state.grace_tasks.clear()

    await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    # Step 1: remove per-AP overrides (APs fall back to neutral profile)
    if protected:
        try:
            await _batch_clear_ap_overrides(site_id, list(protected))
            for ap_mac in protected:
                await _log_event(site_id, "AP_ENABLED", ap_mac=ap_mac, reason="window_end")
        except Exception as exc:
            for ap_mac in protected:
                await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=type(exc).__name__, action="clear_override")

    # Step 2: restore profile to neutral (no radio config)
    try:
        await _update_profile_radio(schedule.off_profile_id, {})
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=None, error=type(exc).__name__, action="profile_restore")

    async with get_lock(site_id):
        state.protected_aps.clear()
        state.total_non_critical_aps = 0
        state.status = "IDLE"

    await _log_event(site_id, "WINDOW_END")
    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {
            "$set": {
                "current_status": "IDLE",
                "protected_ap_macs": [],
                "last_transition_at": datetime.now(timezone.utc),
            }
        }
    )
    await _broadcast_status(site_id, "IDLE")


async def end_off_hours_catchup(schedule: PowerSchedule) -> None:
    """Startup recovery: clear per-AP overrides and restore profile to neutral."""
    site_id = schedule.site_id
    await _log_event(site_id, "CATCHUP_START", direction="on")

    if schedule.protected_ap_macs:
        try:
            await _batch_clear_ap_overrides(site_id, schedule.protected_ap_macs)
            for mac in schedule.protected_ap_macs:
                await _log_event(site_id, "AP_ENABLED", ap_mac=mac, reason="catchup")
        except Exception as exc:
            for mac in schedule.protected_ap_macs:
                await _log_event(site_id, "ERROR", ap_mac=mac, error=type(exc).__name__, action="catchup_clear_override")

    try:
        await _update_profile_radio(schedule.off_profile_id, {})
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=None, error=type(exc).__name__, action="catchup_profile_restore")

    await PowerSchedule.find_one(PowerSchedule.site_id == site_id).update(
        {
            "$set": {
                "current_status": "IDLE",
                "protected_ap_macs": [],
                "last_transition_at": datetime.now(timezone.utc),
            }
        }
    )
    await _broadcast_status(site_id, "IDLE")
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

    # If AP was disabled (no override), add override to re-enable it
    async with get_lock(site_id):
        was_disabled = ap_mac not in state.protected_aps and ap_mac not in schedule.critical_ap_macs

    if was_disabled:
        try:
            await _set_ap_override(site_id, ap_mac)
            async with get_lock(site_id):
                state.protected_aps.add(ap_mac)
            await _log_event(site_id, "AP_ENABLED", ap_mac=ap_mac, reason="client_arrived", client_mac=client_mac)
            await _broadcast_status(site_id, "OFF_HOURS")
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=type(exc).__name__, action="re-enable_on_client")

    # Pre-enable strong neighbors that are still disabled
    async with get_lock(site_id):
        neighbors = state.rf_neighbor_map.get(ap_mac, [])
        to_enable = [
            nbr_mac
            for nbr_mac, rssi in neighbors
            if rssi > schedule.neighbor_rssi_threshold_dbm and nbr_mac not in state.protected_aps
        ]

    if to_enable:
        try:
            await _batch_set_ap_overrides(site_id, to_enable)
            async with get_lock(site_id):
                state.protected_aps.update(to_enable)
            for nbr_mac in to_enable:
                await _log_event(
                    site_id, "AP_ENABLED", ap_mac=nbr_mac, reason="neighbor_coverage", triggering_ap=ap_mac
                )
            await _broadcast_status(site_id, "OFF_HOURS")
        except Exception as exc:
            for nbr_mac in to_enable:
                await _log_event(site_id, "ERROR", ap_mac=nbr_mac, error=type(exc).__name__, action="re-enable_neighbor")

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

    # If AP is protected and now empty, start grace timer to potentially remove override
    async with get_lock(site_id):
        should_start_grace = is_now_empty and ap_mac in state.protected_aps and ap_mac not in state.grace_tasks

    if should_start_grace:
        await _log_event(site_id, "GRACE_TIMER_START", ap_mac=ap_mac, grace_minutes=schedule.grace_period_minutes)
        task = create_background_task(
            _grace_timer(site_id, ap_mac, schedule),
            name=f"grace-{site_id}-{ap_mac}",
        )
        async with get_lock(site_id):
            state.grace_tasks[ap_mac] = task

    await _reevaluate_pending(site_id, state, schedule)


async def _grace_timer(site_id: str, ap_mac: str, schedule: PowerSchedule) -> None:
    """Wait grace period, then remove AP override if still eligible.

    Postcondition invariant: if a client arrives between the pre-API eligibility
    check and the Mist API call completing, the override is immediately restored
    so the AP is never left disabled with an active client.
    """
    await asyncio.sleep(schedule.grace_period_minutes * 60)
    state = get_state(site_id)

    async with get_lock(site_id):
        state.grace_tasks.pop(ap_mac, None)
        if ap_mac not in state.protected_aps:
            return
        if not can_disable(ap_mac, state, schedule):
            return

    # Lock released — Mist API call happens here.
    # A client join event can fire concurrently; _handle_client_join will see
    # ap_mac still in protected_aps and skip re-adding the override (was_disabled=False),
    # so we must detect and correct this after the API call completes.
    try:
        await _clear_ap_override(site_id, ap_mac)
    except Exception as exc:
        await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=type(exc).__name__, action="grace_disable")
        return

    # Re-check under lock: did a client arrive while the API call was in-flight?
    async with get_lock(site_id):
        still_eligible = can_disable(ap_mac, state, schedule)
        if still_eligible:
            state.protected_aps.discard(ap_mac)

    if still_eligible:
        await _log_event(site_id, "GRACE_TIMER_EXPIRED", ap_mac=ap_mac)
        await _log_event(site_id, "AP_DISABLED", ap_mac=ap_mac, reason="grace_expired")
        await _broadcast_status(site_id, "OFF_HOURS")
    else:
        # Client arrived during the API window. The override was already cleared by
        # _clear_ap_override — restore it immediately. ap_mac stays in protected_aps.
        try:
            await _set_ap_override(site_id, ap_mac)
            await _log_event(site_id, "AP_ENABLED", ap_mac=ap_mac, reason="grace_rollback_client_arrived")
            await _broadcast_status(site_id, "OFF_HOURS")
        except Exception as exc:
            await _log_event(site_id, "ERROR", ap_mac=ap_mac, error=type(exc).__name__, action="grace_rollback")


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
            nbr_mac
            for nbr_mac, nbr_rssi in neighbors
            if nbr_rssi > schedule.neighbor_rssi_threshold_dbm and nbr_mac not in state.protected_aps
        ]

    if to_enable:
        try:
            await _batch_set_ap_overrides(site_id, to_enable)
            async with get_lock(site_id):
                state.protected_aps.update(to_enable)
            for nbr_mac in to_enable:
                await _log_event(
                    site_id,
                    "AP_ENABLED",
                    ap_mac=nbr_mac,
                    reason="rssi_pre_enable",
                    client_mac=client_mac,
                    current_ap=ap_mac,
                    rssi=rssi,
                )
            await _broadcast_status(site_id, "OFF_HOURS")
        except Exception as exc:
            for nbr_mac in to_enable:
                await _log_event(site_id, "ERROR", ap_mac=nbr_mac, error=type(exc).__name__, action="rssi_pre_enable")


async def _reevaluate_pending(site_id: str, state: PowerScheduleState, schedule: PowerSchedule) -> None:
    """Check if any protected AP is now eligible to lose its override (start grace timer)."""
    async with get_lock(site_id):
        now_eligible = [
            ap
            for ap in state.protected_aps
            if can_disable(ap, state, schedule) and ap not in state.grace_tasks
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

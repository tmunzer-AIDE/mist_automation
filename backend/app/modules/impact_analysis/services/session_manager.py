"""
Session lifecycle management for Config Change Impact Analysis.

Module-level functions for creating, transitioning, and querying monitoring sessions.
"""

from datetime import datetime, timedelta, timezone

import structlog
from pymongo.errors import DuplicateKeyError

from app.modules.impact_analysis.models import (
    ACTIVE_STATUSES,
    VALID_TRANSITIONS,
    ConfigChangeEvent,
    DeviceIncident,
    DeviceType,
    MonitoringSession,
    SessionStatus,
    TimelineEntry,
    TimelineEntryType,
)

logger = structlog.get_logger(__name__)


async def _merge_into_session(
    existing: MonitoringSession,
    config_event: ConfigChangeEvent,
    duration_minutes: int,
    interval_minutes: int,
) -> MonitoringSession:
    """Atomically merge a config event into an existing session using MongoDB $push/$set.

    Avoids the read-modify-save race where two concurrent events could both read the same
    config_changes array, both append locally, and the second save overwrites the first.
    """
    config_event_dict = config_event.model_dump(mode="json")
    update_ops: dict = {
        "$push": {"config_changes": config_event_dict},
    }
    if existing.status not in {SessionStatus.PENDING, SessionStatus.BASELINE_CAPTURE, SessionStatus.AWAITING_CONFIG}:
        # Already monitoring: reset polls for a fresh monitoring window
        update_ops["$set"] = {
            "duration_minutes": duration_minutes,
            "interval_minutes": interval_minutes,
            "polls_total": max(1, duration_minutes // interval_minutes),
            "polls_completed": 0,
            "sle_snapshots": [],
            "monitoring_started_at": None,
            "monitoring_ends_at": None,
            "updated_at": datetime.now(timezone.utc),
        }
    else:
        # Pre-monitoring: just append the event, don't reset anything
        update_ops["$set"] = {"updated_at": datetime.now(timezone.utc)}

    await MonitoringSession.find_one(MonitoringSession.id == existing.id).update(update_ops)
    # Re-fetch to get updated state for return
    updated = await MonitoringSession.get(existing.id)
    return updated  # type: ignore[return-value]


async def create_or_merge_session(
    *,
    site_id: str,
    site_name: str,
    org_id: str,
    device_mac: str,
    device_name: str,
    device_type: DeviceType,
    config_event: ConfigChangeEvent,
    duration_minutes: int,
    interval_minutes: int,
) -> tuple[MonitoringSession, bool]:
    """Create a new monitoring session or merge into an existing active one.

    Deduplicates by device_mac + active status. If an active session exists for
    the same device, appends the config event and resets polling counters.

    Returns:
        Tuple of (session, is_new) where is_new=True if a fresh session was created.
    """
    existing = await MonitoringSession.find_one(
        {
            "device_mac": device_mac,
            "status": {"$in": [s.value for s in ACTIVE_STATUSES]},
        }
    )

    if existing:
        merged = await _merge_into_session(existing, config_event, duration_minutes, interval_minutes)
        logger.info(
            "session_merged",
            session_id=str(merged.id),
            device_mac=device_mac,
            total_changes=len(merged.config_changes),
        )
        await broadcast_session_update(merged)
        return merged, False

    polls_total = max(1, duration_minutes // interval_minutes)
    session = MonitoringSession(
        site_id=site_id,
        site_name=site_name,
        org_id=org_id,
        device_mac=device_mac,
        device_name=device_name,
        device_type=device_type,
        config_changes=[config_event],
        duration_minutes=duration_minutes,
        interval_minutes=interval_minutes,
        polls_total=polls_total,
    )
    try:
        await session.insert()
    except DuplicateKeyError:
        # Another concurrent request created a session for this device — merge into it
        existing = await MonitoringSession.find_one(
            {
                "device_mac": device_mac,
                "status": {"$in": [s.value for s in ACTIVE_STATUSES]},
            }
        )
        if existing:
            merged = await _merge_into_session(existing, config_event, duration_minutes, interval_minutes)
            logger.info(
                "session_merged_after_race",
                session_id=str(merged.id),
                device_mac=device_mac,
                total_changes=len(merged.config_changes),
            )
            await broadcast_session_update(merged)
            return merged, False
        raise  # Should not happen — re-raise if somehow the session vanished

    logger.info("session_created", session_id=str(session.id), device_mac=device_mac, device_type=device_type)
    await broadcast_session_update(session)
    await _broadcast_summary_update()
    return session, True


async def transition(session: MonitoringSession, new_status: SessionStatus) -> None:
    """Transition a session to a new status with validation.

    Raises ValueError if the transition is not allowed.
    """
    allowed = VALID_TRANSITIONS.get(session.status, set())
    if new_status not in allowed:
        raise ValueError(f"Cannot transition from {session.status} to {new_status}")

    old_status = session.status
    session.status = new_status

    # Set completed_at for terminal states
    if new_status in {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED}:
        session.completed_at = datetime.now(timezone.utc)

    session.update_timestamp()
    await session.save()

    # Record transition in timeline
    await append_timeline_entry(
        session,
        TimelineEntry(
            type=TimelineEntryType.STATUS_CHANGE,
            title=f"{old_status.value} \u2192 {new_status.value}",
            severity="info",
        ),
    )

    logger.info(
        "session_transition",
        session_id=str(session.id),
        from_status=old_status,
        to_status=new_status,
    )
    await broadcast_session_update(session)
    await _broadcast_summary_update()


async def config_applied(
    session: MonitoringSession,
    config_event: ConfigChangeEvent | None = None,
) -> None:
    """Handle CONFIGURED event arriving during AWAITING_CONFIG.

    Appends the CONFIGURED event, records the apply timestamp, and
    transitions the session to MONITORING.
    """
    if config_event:
        session.config_changes.append(config_event)
    session.config_applied_at = datetime.now(timezone.utc)
    session.update_timestamp()
    await session.save()
    await transition(session, SessionStatus.MONITORING)


async def add_incident(session: MonitoringSession, incident: DeviceIncident) -> None:
    """Append an incident to the session and broadcast the update."""
    from app.core.websocket import ws_manager

    session.incidents.append(incident)
    session.update_timestamp()
    await session.save()
    logger.info(
        "incident_added",
        session_id=str(session.id),
        event_type=incident.event_type,
        severity=incident.severity,
        device_mac=incident.device_mac,
    )
    await broadcast_session_update(session)
    await ws_manager.broadcast(
        f"impact:{session.id}",
        {
            "type": "incident_added",
            "data": {
                "event_type": incident.event_type,
                "device_name": incident.device_name,
                "device_mac": incident.device_mac,
                "severity": incident.severity,
                "is_revert": incident.is_revert,
                "timestamp": incident.timestamp.isoformat(),
            },
        },
    )


async def resolve_incident(session: MonitoringSession, event_type: str, device_mac: str) -> None:
    """Mark matching unresolved incidents as resolved."""
    from app.core.websocket import ws_manager

    now = datetime.now(timezone.utc)
    resolved_count = 0
    for incident in session.incidents:
        if incident.event_type == event_type and incident.device_mac == device_mac and not incident.resolved:
            incident.resolved = True
            incident.resolved_at = now
            resolved_count += 1

    if resolved_count > 0:
        session.update_timestamp()
        await session.save()
        logger.info(
            "incidents_resolved",
            session_id=str(session.id),
            event_type=event_type,
            device_mac=device_mac,
            count=resolved_count,
        )
        await broadcast_session_update(session)
        await ws_manager.broadcast(
            f"impact:{session.id}",
            {
                "type": "incident_resolved",
                "data": {
                    "event_type": event_type,
                    "device_mac": device_mac,
                    "resolved_at": now.isoformat(),
                },
            },
        )


async def cancel_session(session_id: str) -> MonitoringSession | None:
    """Cancel an active session. Returns the updated session or None if not found/not active."""
    session = await MonitoringSession.get(session_id)
    if not session:
        return None
    if session.status not in ACTIVE_STATUSES:
        return None
    await transition(session, SessionStatus.CANCELLED)
    return session


async def escalate_impact(session: MonitoringSession, severity: str) -> None:
    """Escalate impact severity — only goes up, never down."""
    from app.core.websocket import ws_manager

    severity_order = {"none": 0, "info": 1, "warning": 2, "critical": 3}
    current = severity_order.get(session.impact_severity, 0)
    new = severity_order.get(severity, 0)
    if new <= current:
        return  # Don't downgrade

    session.impact_severity = severity
    session.update_timestamp()
    await session.save()
    await broadcast_session_update(session)
    await ws_manager.broadcast(
        f"impact:{session.id}",
        {"type": "impact_severity_changed", "data": {"severity": severity}},
    )


async def get_session_summary() -> dict[str, int]:
    """Get dashboard summary counts using $facet aggregation.

    Returns dict with keys: active, alert, completed_24h, total.
    """
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(hours=24)

    pipeline = [
        {
            "$facet": {
                "total": [{"$count": "n"}],
                "active": [
                    {"$match": {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}}},
                    {"$count": "n"},
                ],
                "impacted": [
                    {"$match": {"impact_severity": {"$ne": "none"}}},
                    {"$count": "n"},
                ],
                "completed_24h": [
                    {
                        "$match": {
                            "status": SessionStatus.COMPLETED.value,
                            "completed_at": {"$gte": twenty_four_hours_ago},
                        }
                    },
                    {"$count": "n"},
                ],
            }
        }
    ]

    results = await MonitoringSession.aggregate(pipeline).to_list()
    row = results[0] if results else {}

    def _extract(key: str) -> int:
        bucket = row.get(key, [])
        return bucket[0]["n"] if bucket else 0

    return {
        "active": _extract("active"),
        "impacted": _extract("impacted"),
        "completed_24h": _extract("completed_24h"),
        "total": _extract("total"),
    }


# ── Timeline ─────────────────────────────────────────────────────────────


async def append_timeline_entry(session: MonitoringSession, entry: TimelineEntry) -> None:
    """Atomically push a timeline entry and broadcast via WebSocket.

    Uses MongoDB $push so parallel writers (validation branch, SLE branch,
    event handler) never overwrite each other's entries.
    """
    from app.core.websocket import ws_manager

    entry_dict = entry.model_dump(mode="json")
    await MonitoringSession.find_one(MonitoringSession.id == session.id).update({"$push": {"timeline": entry_dict}})
    await ws_manager.broadcast(
        f"impact:{session.id}",
        {"type": "timeline_entry", "data": entry_dict},
    )


# ── WebSocket broadcasting ────────────────────────────────────────────────


async def broadcast_session_update(session: MonitoringSession) -> None:
    """Broadcast session state to subscribers on impact:{session.id}."""
    from app.core.websocket import ws_manager

    channel = f"impact:{session.id}"
    await ws_manager.broadcast(
        channel,
        {
            "type": "session_update",
            "data": {
                "id": str(session.id),
                "status": session.status.value,
                "impact_severity": session.impact_severity,
                "progress": session.progress,
                "incident_count": len(session.incidents),
                "polls_completed": session.polls_completed,
                "polls_total": session.polls_total,
            },
        },
    )


async def _broadcast_summary_update() -> None:
    """Broadcast updated summary counts to the impact:summary channel."""
    from app.core.websocket import ws_manager

    summary = await get_session_summary()
    await ws_manager.broadcast(
        "impact:summary",
        {
            "type": "summary_update",
            "data": summary,
        },
    )

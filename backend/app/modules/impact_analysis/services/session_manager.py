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
)

logger = structlog.get_logger(__name__)


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
        existing.config_changes.append(config_event)
        existing.duration_minutes = duration_minutes
        existing.interval_minutes = interval_minutes
        existing.polls_total = max(1, duration_minutes // interval_minutes)
        existing.polls_completed = 0
        existing.sle_snapshots = []
        existing.monitoring_started_at = None
        existing.monitoring_ends_at = None
        existing.update_timestamp()
        await existing.save()
        logger.info(
            "session_merged",
            session_id=str(existing.id),
            device_mac=device_mac,
            total_changes=len(existing.config_changes),
        )
        await broadcast_session_update(existing)
        return existing, False

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
            existing.config_changes.append(config_event)
            existing.duration_minutes = duration_minutes
            existing.interval_minutes = interval_minutes
            existing.polls_total = max(1, duration_minutes // interval_minutes)
            existing.polls_completed = 0
            existing.sle_snapshots = []
            existing.monitoring_started_at = None
            existing.monitoring_ends_at = None
            existing.update_timestamp()
            await existing.save()
            logger.info(
                "session_merged_after_race",
                session_id=str(existing.id),
                device_mac=device_mac,
                total_changes=len(existing.config_changes),
            )
            await broadcast_session_update(existing)
            return existing, False
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
    if new_status in {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED, SessionStatus.ALERT}:
        session.completed_at = datetime.now(timezone.utc)

    session.update_timestamp()
    await session.save()
    logger.info(
        "session_transition",
        session_id=str(session.id),
        from_status=old_status,
        to_status=new_status,
    )
    await broadcast_session_update(session)
    await _broadcast_summary_update()


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
    if session.status not in ACTIVE_STATUSES and session.status != SessionStatus.ALERT:
        return None
    await transition(session, SessionStatus.CANCELLED)
    return session


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
                "alert": [
                    {"$match": {"status": SessionStatus.ALERT.value}},
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
        "alert": _extract("alert"),
        "completed_24h": _extract("completed_24h"),
        "total": _extract("total"),
    }


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

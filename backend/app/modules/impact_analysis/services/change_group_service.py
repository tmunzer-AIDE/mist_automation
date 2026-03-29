"""
Change Group lifecycle management.

Creates, updates, and queries ChangeGroup documents that correlate
monitoring sessions triggered by the same audit event.
"""

from datetime import datetime, timedelta, timezone

import structlog
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from app.modules.impact_analysis.change_group import (
    ChangeGroup,
    DeviceSummary,
    DeviceTypeCounts,
    GroupSummary,
    IncidentSummary,
    SLEDelta,
    ValidationCheckSummary,
)
from app.modules.impact_analysis.models import (
    ACTIVE_STATUSES,
    MonitoringSession,
    SessionStatus,
    TimelineEntry,
    TimelineEntryType,
)

logger = structlog.get_logger(__name__)

# Terminal session statuses
_TERMINAL_STATUSES = {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.CANCELLED}

# Severity ordering for worst-severity computation
_SEVERITY_ORDER = {"none": 0, "info": 1, "warning": 2, "critical": 3}


async def get_or_create_group(
    *,
    audit_id: str,
    org_id: str,
    site_id: str | None,
    change_source: str,
    change_description: str,
    triggered_by: str | None,
) -> tuple[ChangeGroup, bool]:
    """Find an existing group by audit_id or create a new one.

    Returns (group, is_new).
    """
    existing = await ChangeGroup.find_one({"audit_id": audit_id})
    if existing:
        return existing, False

    group = ChangeGroup(
        audit_id=audit_id,
        org_id=org_id,
        site_id=site_id,
        change_source=change_source,
        change_description=change_description,
        triggered_by=triggered_by,
    )
    try:
        await group.insert()
    except DuplicateKeyError:
        existing = await ChangeGroup.find_one({"audit_id": audit_id})
        if existing:
            return existing, False
        raise

    # Timeline entry for creation
    entry = TimelineEntry(
        type=TimelineEntryType.STATUS_CHANGE,
        title=f"Change group created: {change_description}",
        severity="info",
    )
    await ChangeGroup.find_one(ChangeGroup.id == group.id).update(
        {"$push": {"timeline": entry.model_dump(mode="json")}}
    )

    logger.info("change_group_created", group_id=str(group.id), audit_id=audit_id)
    return group, True


async def add_session_to_group(group_id: PydanticObjectId, session_id: PydanticObjectId) -> None:
    """Append a session ID to the group's session_ids list."""
    await ChangeGroup.find_one(ChangeGroup.id == group_id).update(
        {
            "$addToSet": {"session_ids": session_id},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        }
    )


async def update_summary(change_group_id: PydanticObjectId) -> None:
    """Recompute the group summary from all child sessions and broadcast."""
    from app.core.websocket import ws_manager

    group = await ChangeGroup.get(change_group_id)
    if not group or not group.session_ids:
        return

    # Fetch child sessions (projected to needed fields)
    sessions = await MonitoringSession.find({"_id": {"$in": group.session_ids}}).to_list()

    if not sessions:
        return

    # Build per-device summaries
    devices: list[DeviceSummary] = []
    by_type: dict[str, DeviceTypeCounts] = {}
    worst_severity = "none"
    validation_agg: dict[str, dict[str, int]] = {}  # check_name -> {passed, failed, skipped}
    sle_agg: dict[str, list[SLEDelta]] = {}  # metric -> list of deltas

    for s in sessions:
        dtype = s.device_type.value if hasattr(s.device_type, "value") else str(s.device_type)
        status_val = s.status.value if hasattr(s.status, "value") else str(s.status)

        # Per-device summary
        failed_checks: list[str] = []
        if s.validation_results and isinstance(s.validation_results.get("results"), dict):
            for check_name, result in s.validation_results["results"].items():
                if isinstance(result, dict) and result.get("status") == "fail":
                    failed_checks.append(check_name)

        active_incidents: list[IncidentSummary] = []
        for inc in s.incidents:
            active_incidents.append(
                IncidentSummary(
                    type=inc.event_type,
                    severity=inc.severity,
                    timestamp=inc.timestamp,
                    resolved=inc.resolved,
                )
            )

        worst_sle: SLEDelta | None = None
        if s.sle_delta and isinstance(s.sle_delta.get("metrics"), dict):
            worst_delta_pct = 0.0
            for metric_name, metric_data in s.sle_delta["metrics"].items():
                if isinstance(metric_data, dict):
                    delta = metric_data.get("change_pct", 0.0)
                    if isinstance(delta, (int, float)) and delta < worst_delta_pct:
                        worst_delta_pct = delta
                        worst_sle = SLEDelta(
                            metric=metric_name,
                            baseline=metric_data.get("baseline", 0.0),
                            current=metric_data.get("current", 0.0),
                            delta_pct=delta,
                        )

        devices.append(
            DeviceSummary(
                session_id=s.id,
                device_mac=s.device_mac,
                device_name=s.device_name,
                device_type=dtype,
                site_name=s.site_name,
                status=status_val,
                impact_severity=s.impact_severity,
                failed_checks=failed_checks,
                active_incidents=active_incidents,
                worst_sle_delta=worst_sle,
            )
        )

        # Aggregate by type
        if dtype not in by_type:
            by_type[dtype] = DeviceTypeCounts()
        counts = by_type[dtype]
        counts.total += 1
        if s.status in ACTIVE_STATUSES:
            counts.monitoring += 1
        elif s.status in _TERMINAL_STATUSES:
            counts.completed += 1
        if s.impact_severity != "none":
            counts.impacted += 1

        # Worst severity
        if _SEVERITY_ORDER.get(s.impact_severity, 0) > _SEVERITY_ORDER.get(worst_severity, 0):
            worst_severity = s.impact_severity

        # Aggregate validation
        if s.validation_results and isinstance(s.validation_results.get("results"), dict):
            for check_name, result in s.validation_results["results"].items():
                if check_name not in validation_agg:
                    validation_agg[check_name] = {"passed": 0, "failed": 0, "skipped": 0}
                if isinstance(result, dict):
                    st = result.get("status", "skipped")
                    if st == "pass":
                        validation_agg[check_name]["passed"] += 1
                    elif st == "fail":
                        validation_agg[check_name]["failed"] += 1
                    else:
                        validation_agg[check_name]["skipped"] += 1

        # Aggregate SLE
        if s.sle_delta and isinstance(s.sle_delta.get("metrics"), dict):
            for metric_name, metric_data in s.sle_delta["metrics"].items():
                if isinstance(metric_data, dict):
                    delta = SLEDelta(
                        metric=metric_name,
                        baseline=metric_data.get("baseline", 0.0),
                        current=metric_data.get("current", 0.0),
                        delta_pct=metric_data.get("change_pct", 0.0),
                    )
                    sle_agg.setdefault(metric_name, []).append(delta)

    # Compute SLE summary (worst delta per metric)
    sle_summary: dict[str, SLEDelta] = {}
    for metric_name, deltas in sle_agg.items():
        worst = min(deltas, key=lambda d: d.delta_pct)
        sle_summary[metric_name] = worst

    # Compute validation summary
    validation_summary = [ValidationCheckSummary(check_name=name, **counts) for name, counts in validation_agg.items()]

    # Compute group status
    all_terminal = all(s.status in _TERMINAL_STATUSES for s in sessions)
    any_terminal = any(s.status in _TERMINAL_STATUSES for s in sessions)
    if all_terminal:
        group_status = "completed"
    elif any_terminal:
        group_status = "partial"
    else:
        group_status = "monitoring"

    now = datetime.now(timezone.utc)
    summary = GroupSummary(
        total_devices=len(sessions),
        by_type=by_type,
        worst_severity=worst_severity,
        validation_summary=validation_summary,
        sle_summary=sle_summary,
        devices=devices,
        status=group_status,
        last_updated=now,
    )

    old_status = group.summary.status if group.summary else "monitoring"

    await ChangeGroup.find_one(ChangeGroup.id == group.id).update(
        {"$set": {"summary": summary.model_dump(mode="json"), "updated_at": now}}
    )

    # Broadcast group update
    await ws_manager.broadcast(
        f"impact:group:{group.id}",
        {
            "type": "group_update",
            "data": summary.model_dump(mode="json"),
        },
    )

    # Broadcast to summary channel
    await _broadcast_summary_update()

    # If group just completed, trigger group-level AI analysis
    if group_status == "completed" and old_status != "completed":
        from app.core.tasks import create_background_task

        create_background_task(
            trigger_group_ai_analysis(str(group.id)),
            name=f"group-ai-{group.id}",
        )

    logger.debug(
        "change_group_summary_updated",
        group_id=str(group.id),
        total_devices=len(sessions),
        status=group_status,
        worst_severity=worst_severity,
    )


async def trigger_group_ai_analysis(group_id: str) -> None:
    """Trigger AI analysis for a completed change group."""
    from app.core.websocket import ws_manager

    group = await ChangeGroup.get(PydanticObjectId(group_id))
    if not group:
        return

    # Atomic claim
    claim = await ChangeGroup.find_one(
        ChangeGroup.id == group.id,
        {"ai_analysis_in_progress": {"$ne": True}},
    ).update({"$set": {"ai_analysis_in_progress": True}})
    if not claim or claim.modified_count == 0:
        return

    try:
        from app.modules.impact_analysis.services.analysis_service import analyze_change_group

        result = await analyze_change_group(group)

        await ChangeGroup.find_one(ChangeGroup.id == group.id).update(
            {"$set": {"ai_assessment": result, "ai_analysis_in_progress": False}}
        )

        has_impact = result.get("has_impact", False) if result else False
        ai_severity = result.get("severity", "info") if result else "info"

        entry = TimelineEntry(
            type=TimelineEntryType.AI_ANALYSIS,
            title="Group AI analysis (final)",
            severity=ai_severity if has_impact else "info",
            data={
                "trigger": "group_final",
                "has_impact": has_impact,
                "severity": ai_severity,
                "summary": (result.get("summary", "")[:500] if result else ""),
                "source": result.get("source", "unknown") if result else "unknown",
            },
        )
        await ChangeGroup.find_one(ChangeGroup.id == group.id).update(
            {"$push": {"timeline": entry.model_dump(mode="json")}}
        )

        await ws_manager.broadcast(
            f"impact:group:{group.id}",
            {
                "type": "ai_analysis_completed",
                "data": {
                    "has_impact": has_impact,
                    "severity": ai_severity,
                    "summary": (result.get("summary", "")[:500] if result else ""),
                },
            },
        )

    except Exception as e:
        logger.warning("group_ai_analysis_failed", group_id=group_id, error=str(e))
        await ChangeGroup.find_one(ChangeGroup.id == PydanticObjectId(group_id)).update(
            {
                "$set": {
                    "ai_assessment_error": "AI analysis unavailable",
                    "ai_analysis_in_progress": False,
                }
            }
        )


async def get_group_summary_counts() -> dict[str, int]:
    """Get dashboard-level group counts using $facet."""
    now = datetime.now(timezone.utc)
    twenty_four_hours_ago = now - timedelta(hours=24)

    pipeline = [
        {
            "$facet": {
                "active_groups": [
                    {"$match": {"summary.status": {"$in": ["monitoring", "partial"]}}},
                    {"$count": "n"},
                ],
                "impacted_groups_24h": [
                    {
                        "$match": {
                            "summary.worst_severity": {"$ne": "none"},
                            "summary.status": "completed",
                            "updated_at": {"$gte": twenty_four_hours_ago},
                        }
                    },
                    {"$count": "n"},
                ],
            }
        }
    ]
    results = await ChangeGroup.aggregate(pipeline).to_list()
    row = results[0] if results else {}

    def _extract(key: str) -> int:
        bucket = row.get(key, [])
        return bucket[0]["n"] if bucket else 0

    return {
        "active_groups": _extract("active_groups"),
        "impacted_groups_24h": _extract("impacted_groups_24h"),
    }


async def _broadcast_summary_update() -> None:
    """Broadcast updated summary counts including group stats."""
    from app.core.websocket import ws_manager
    from app.modules.impact_analysis.services.session_manager import get_session_summary

    session_summary = await get_session_summary()
    group_summary = await get_group_summary_counts()

    await ws_manager.broadcast(
        "impact:summary",
        {
            "type": "summary_update",
            "data": {**session_summary, **group_summary},
        },
    )

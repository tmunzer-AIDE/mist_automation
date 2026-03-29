# Impact Analysis Change Groups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group impact analysis monitoring sessions by shared `audit_id` so operators see "one change, N devices" instead of N independent sessions.

**Architecture:** Additive `ChangeGroup` Beanie Document keyed by `audit_id`, referencing existing per-device `MonitoringSession` docs. Group maintains a live aggregate summary (recomputed on every child state change). AI analysis runs once per group at completion. Frontend shows groups as primary list view with drill-down to per-device sessions.

**Tech Stack:** Python 3.10+, FastAPI, Beanie/MongoDB, Angular 21, Material, signals, WebSocket

**Spec:** `docs/superpowers/specs/2026-03-29-impact-analysis-change-groups-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/app/modules/impact_analysis/change_group.py` | ChangeGroup document, sub-models |
| Create | `backend/app/modules/impact_analysis/services/change_group_service.py` | Group lifecycle, summary recomputation |
| Modify | `backend/app/modules/impact_analysis/models.py:146` | Add `change_group_id` field to MonitoringSession |
| Modify | `backend/app/modules/__init__.py:133-141` | Register ChangeGroup model |
| Modify | `backend/app/modules/impact_analysis/workers/event_handler.py:281-326` | Wire group creation in `_handle_pre_config_trigger` and `_handle_configured` |
| Modify | `backend/app/modules/impact_analysis/services/session_manager.py` | Call `update_summary` on state changes |
| Modify | `backend/app/modules/impact_analysis/schemas.py` | Add group response/request schemas |
| Modify | `backend/app/modules/impact_analysis/router.py` | Add group endpoints |
| Modify | `backend/app/modules/impact_analysis/workers/monitoring_worker.py:853-922` | Trigger group AI on group completion |
| Modify | `backend/app/modules/impact_analysis/services/analysis_service.py:131-154` | Add group-level analysis function and prompt |
| Modify | `frontend/src/app/features/impact-analysis/models/impact-analysis.model.ts` | Add group TypeScript interfaces |
| Modify | `frontend/src/app/core/services/impact-analysis.service.ts` | Add group API methods |
| Modify | `frontend/src/app/features/impact-analysis/impact-analysis.routes.ts` | Add group detail route |
| Modify | `frontend/src/app/features/impact-analysis/session-list/session-list.component.ts` | Show groups as primary view |
| Modify | `frontend/src/app/features/impact-analysis/session-list/session-list.component.html` | Group row template |
| Create | `frontend/src/app/features/impact-analysis/group-detail/group-detail.component.ts` | Group detail page |
| Modify | `frontend/src/app/features/impact-analysis/session-detail/session-detail.component.ts` | Back-link to parent group |
| Modify | `frontend/src/app/features/impact-analysis/session-detail/session-detail.component.html` | Breadcrumb to group |

---

## Task 1: ChangeGroup Data Model

**Files:**
- Create: `backend/app/modules/impact_analysis/models/change_group.py`
- Modify: `backend/app/modules/impact_analysis/models.py:146`
- Modify: `backend/app/modules/__init__.py:133-141`

- [ ] **Step 1: Create the ChangeGroup model file**

Create `backend/app/modules/impact_analysis/change_group.py`:

```python
"""
Change Group model — groups monitoring sessions triggered by the same audit event.
"""

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from app.models.mixins import TimestampMixin
from app.modules.impact_analysis.models import TimelineEntry


class IncidentSummary(BaseModel):
    """Abbreviated incident for the group summary."""

    type: str
    severity: str
    timestamp: datetime
    resolved: bool = False


class SLEDelta(BaseModel):
    """SLE metric delta for a single metric."""

    metric: str
    baseline: float
    current: float
    delta_pct: float


class DeviceSummary(BaseModel):
    """Per-device summary within a change group."""

    session_id: PydanticObjectId
    device_mac: str
    device_name: str
    device_type: str  # "ap", "switch", "gateway"
    site_name: str
    status: str
    impact_severity: str
    failed_checks: list[str] = Field(default_factory=list)
    active_incidents: list[IncidentSummary] = Field(default_factory=list)
    worst_sle_delta: SLEDelta | None = None


class DeviceTypeCounts(BaseModel):
    """Counts per device type."""

    total: int = 0
    monitoring: int = 0
    completed: int = 0
    impacted: int = 0


class ValidationCheckSummary(BaseModel):
    """Aggregate pass/fail/skip counts for a single validation check."""

    check_name: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class GroupSummary(BaseModel):
    """Live aggregate summary of all child sessions."""

    total_devices: int = 0
    by_type: dict[str, DeviceTypeCounts] = Field(default_factory=dict)
    worst_severity: str = "none"
    validation_summary: list[ValidationCheckSummary] = Field(default_factory=list)
    sle_summary: dict[str, SLEDelta] = Field(default_factory=dict)
    devices: list[DeviceSummary] = Field(default_factory=list)
    status: str = "monitoring"  # "monitoring", "partial", "completed"
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChangeGroup(TimestampMixin, Document):
    """Groups monitoring sessions triggered by the same configuration change (audit_id)."""

    audit_id: str = Field(..., description="Correlation key from Mist webhooks")
    org_id: str = Field(..., description="Mist organization ID")
    site_id: str | None = Field(default=None, description="Site ID (None for org-level changes)")

    # What triggered this
    change_source: str = Field(default="", description="e.g. org_template, site_settings")
    change_description: str = Field(default="", description="Human-readable, e.g. Template 'Branch-AP' modified")
    triggered_by: str | None = Field(default=None, description="User/method from audit event")
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Child sessions
    session_ids: list[PydanticObjectId] = Field(default_factory=list)

    # Live aggregate summary
    summary: GroupSummary = Field(default_factory=GroupSummary)

    # AI assessment (one per group)
    ai_assessment: dict | None = Field(default=None, description="LLM-generated group impact assessment")
    ai_assessment_error: str | None = Field(default=None)
    ai_analysis_in_progress: bool = Field(default=False)
    conversation_thread_id: str | None = Field(default=None)

    # Group-level timeline (creation, AI analysis, severity escalations)
    timeline: list[TimelineEntry] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "change_groups"
        indexes = [
            IndexModel([("audit_id", 1)], unique=True),
            IndexModel([("org_id", 1)]),
            IndexModel([("summary.status", 1)]),
            IndexModel([("created_at", -1)]),
        ]
```

- [ ] **Step 2: Add `change_group_id` to MonitoringSession**

In `backend/app/modules/impact_analysis/models.py`, add after line 156 (`device_mist_id` field):

```python
    # Change group reference (if this session is part of a grouped config change)
    change_group_id: PydanticObjectId | None = Field(
        default=None, description="Parent ChangeGroup ID (if part of a multi-device change)"
    )
```

Also add `PydanticObjectId` to the beanie import at line 11:

```python
from beanie import Document, PydanticObjectId
```

- [ ] **Step 3: Register ChangeGroup in module init**

In `backend/app/modules/__init__.py`, update the `impact_analysis` AppModule entry (around line 133) to include the new model:

```python
    AppModule(
        name="impact_analysis",
        router_module="app.modules.impact_analysis.router",
        model_imports=[
            ("app.modules.impact_analysis.models", "MonitoringSession"),
            ("app.modules.impact_analysis.models", "SessionLogEntry"),
            ("app.modules.impact_analysis.models.change_group", "ChangeGroup"),
        ],
        tags=["Impact Analysis"],
    ),
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/impact_analysis/change_group.py backend/app/modules/impact_analysis/models.py backend/app/modules/__init__.py
git commit -m "feat(impact): add ChangeGroup model and change_group_id on MonitoringSession"
```

---

## Task 2: ChangeGroupService

**Files:**
- Create: `backend/app/modules/impact_analysis/services/change_group_service.py`

- [ ] **Step 1: Create the change group service**

Create `backend/app/modules/impact_analysis/services/change_group_service.py`:

```python
"""
Change Group lifecycle management.

Creates, updates, and queries ChangeGroup documents that correlate
monitoring sessions triggered by the same audit event.
"""

from datetime import datetime, timezone
from typing import Any

import structlog
from beanie import PydanticObjectId

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
    await group.insert()

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
    sessions = await MonitoringSession.find(
        {"_id": {"$in": group.session_ids}}
    ).to_list()

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
    validation_summary = [
        ValidationCheckSummary(check_name=name, **counts)
        for name, counts in validation_agg.items()
    ]

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
    from datetime import timedelta

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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/modules/impact_analysis/services/change_group_service.py
git commit -m "feat(impact): add ChangeGroupService with lifecycle, summary, and AI trigger"
```

---

## Task 3: Backend Schemas

**Files:**
- Modify: `backend/app/modules/impact_analysis/schemas.py`

- [ ] **Step 1: Add group schemas**

Append the following at the end of `backend/app/modules/impact_analysis/schemas.py` (after the `SessionChatResponse` class at line 205):

```python


# ── Change Group schemas ─────────────────────────────────────────────────


class IncidentSummaryResponse(BaseModel):
    type: str
    severity: str
    timestamp: datetime
    resolved: bool = False


class SLEDeltaResponse(BaseModel):
    metric: str
    baseline: float
    current: float
    delta_pct: float


class DeviceSummaryResponse(BaseModel):
    """Per-device summary within a change group."""

    session_id: str
    device_mac: str
    device_name: str
    device_type: str
    site_name: str
    status: str
    impact_severity: str
    failed_checks: list[str] = Field(default_factory=list)
    active_incidents: list[IncidentSummaryResponse] = Field(default_factory=list)
    worst_sle_delta: SLEDeltaResponse | None = None


class DeviceTypeCountsResponse(BaseModel):
    total: int = 0
    monitoring: int = 0
    completed: int = 0
    impacted: int = 0


class ValidationCheckSummaryResponse(BaseModel):
    check_name: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class GroupSummaryResponse(BaseModel):
    total_devices: int = 0
    by_type: dict[str, DeviceTypeCountsResponse] = Field(default_factory=dict)
    worst_severity: str = "none"
    validation_summary: list[ValidationCheckSummaryResponse] = Field(default_factory=list)
    sle_summary: dict[str, SLEDeltaResponse] = Field(default_factory=dict)
    devices: list[DeviceSummaryResponse] = Field(default_factory=list)
    status: str = "monitoring"
    last_updated: datetime | None = None


class ChangeGroupResponse(BaseModel):
    """Summary view for group list."""

    id: str
    audit_id: str
    org_id: str
    site_id: str | None = None
    change_source: str
    change_description: str
    triggered_by: str | None = None
    triggered_at: datetime
    session_count: int
    summary: GroupSummaryResponse
    ai_assessment: dict | None = None
    ai_assessment_error: str | None = None
    created_at: datetime
    updated_at: datetime


class ChangeGroupDetailResponse(ChangeGroupResponse):
    """Full detail view including timeline."""

    timeline: list[TimelineEntryResponse] = Field(default_factory=list)


class ChangeGroupListResponse(BaseModel):
    """Paginated list of change groups."""

    groups: list[ChangeGroupResponse]
    total: int
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/modules/impact_analysis/schemas.py
git commit -m "feat(impact): add ChangeGroup request/response schemas"
```

---

## Task 4: Wire Group Creation in Event Handler

**Files:**
- Modify: `backend/app/modules/impact_analysis/workers/event_handler.py`

- [ ] **Step 1: Add group creation helper**

Add a helper function after the `_build_config_event` function (after line 234) in `event_handler.py`:

```python
async def _ensure_change_group(
    audit_id: str | None,
    org_id: str,
    site_id: str,
    site_name: str,
    event_type: str,
    payload: dict[str, Any],
    session_id: PydanticObjectId,
) -> PydanticObjectId | None:
    """Create or find a ChangeGroup for this audit_id and link the session."""
    if not audit_id:
        return None

    from app.modules.impact_analysis.services import change_group_service

    # Infer change source from event type
    if "AP_" in event_type:
        change_source = "ap_config"
    elif "SW_" in event_type:
        change_source = "switch_config"
    elif "GW_" in event_type:
        change_source = "gateway_config"
    else:
        change_source = "config"

    # Build description from audit data if available
    change_description = payload.get("text") or f"{event_type} at {site_name}"

    triggered_by = payload.get("commit_user") or payload.get("admin_name") or None

    group, _is_new = await change_group_service.get_or_create_group(
        audit_id=audit_id,
        org_id=org_id,
        site_id=site_id,
        change_source=change_source,
        change_description=change_description,
        triggered_by=triggered_by,
    )

    await change_group_service.add_session_to_group(group.id, session_id)
    return group.id
```

- [ ] **Step 2: Update `_handle_pre_config_trigger` to assign group**

In `_handle_pre_config_trigger` (starting at line 281), after the session is created/merged (around line 307), add group assignment. After the `await _add_timeline_and_tag(...)` call at line 310:

```python
    # Assign to change group if audit_id present
    audit_id = payload.get("audit_id")
    if audit_id and session.change_group_id is None:
        group_id = await _ensure_change_group(
            audit_id=audit_id,
            org_id=org_id,
            site_id=site_id,
            site_name=site_name,
            event_type=event_type,
            payload=payload,
            session_id=session.id,
        )
        if group_id:
            await MonitoringSession.find_one(MonitoringSession.id == session.id).update(
                {"$set": {"change_group_id": group_id}}
            )
            session.change_group_id = group_id
```

- [ ] **Step 3: Update `_handle_configured` to assign group**

Apply the same pattern in `_handle_configured` (starting at line 329). After the session is created or transitioned, add the same group assignment block. Find the section where a new session is created as a fallback trigger (around the `create_or_merge_session` call) and add the same group assignment code after it.

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/impact_analysis/workers/event_handler.py
git commit -m "feat(impact): wire ChangeGroup creation in event handler"
```

---

## Task 5: Session Manager Integration

**Files:**
- Modify: `backend/app/modules/impact_analysis/services/session_manager.py`

- [ ] **Step 1: Add group summary update calls**

The goal: whenever session state changes (transition, incident, severity escalation), also update the parent group summary. Add a helper at the bottom of `session_manager.py`:

```python
async def _update_group_summary(session: MonitoringSession) -> None:
    """If this session belongs to a change group, recompute the group summary."""
    if not session.change_group_id:
        return
    try:
        from app.modules.impact_analysis.services import change_group_service

        await change_group_service.update_summary(session.change_group_id)
    except Exception as e:
        logger.warning("group_summary_update_failed", session_id=str(session.id), error=str(e))
```

- [ ] **Step 2: Call `_update_group_summary` from `transition()`**

At the end of the `transition()` function (after line 197, after `await _broadcast_summary_update()`), add:

```python
    await _update_group_summary(session)
```

- [ ] **Step 3: Call `_update_group_summary` from `add_incident()`**

At the end of `add_incident()` (after the WS broadcast at line 248), add:

```python
    await _update_group_summary(session)
```

- [ ] **Step 4: Call `_update_group_summary` from `escalate_impact()`**

At the end of `escalate_impact()` (after the WS broadcast at line 327), add:

```python
    await _update_group_summary(session)
```

- [ ] **Step 5: Call `_update_group_summary` from `resolve_incident()`**

At the end of `resolve_incident()` (after the WS broadcast at line 296, inside the `if resolved_count > 0:` block), add:

```python
        await _update_group_summary(session)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/modules/impact_analysis/services/session_manager.py
git commit -m "feat(impact): trigger group summary recomputation on session state changes"
```

---

## Task 6: Group API Endpoints

**Files:**
- Modify: `backend/app/modules/impact_analysis/router.py`

- [ ] **Step 1: Add group response helper**

Add after the existing `_session_to_detail_response` helper (around line 136):

```python
def _group_to_response(group: "ChangeGroup") -> "ChangeGroupResponse":
    """Build a ChangeGroupResponse from a ChangeGroup document."""
    from app.modules.impact_analysis.schemas import ChangeGroupResponse, GroupSummaryResponse

    return ChangeGroupResponse(
        id=str(group.id),
        audit_id=group.audit_id,
        org_id=group.org_id,
        site_id=group.site_id,
        change_source=group.change_source,
        change_description=group.change_description,
        triggered_by=group.triggered_by,
        triggered_at=group.triggered_at,
        session_count=len(group.session_ids),
        summary=GroupSummaryResponse(**group.summary.model_dump(mode="json")),
        ai_assessment=group.ai_assessment,
        ai_assessment_error=group.ai_assessment_error,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _group_to_detail_response(group: "ChangeGroup") -> "ChangeGroupDetailResponse":
    """Build a ChangeGroupDetailResponse from a ChangeGroup document."""
    from app.modules.impact_analysis.schemas import ChangeGroupDetailResponse, GroupSummaryResponse

    return ChangeGroupDetailResponse(
        id=str(group.id),
        audit_id=group.audit_id,
        org_id=group.org_id,
        site_id=group.site_id,
        change_source=group.change_source,
        change_description=group.change_description,
        triggered_by=group.triggered_by,
        triggered_at=group.triggered_at,
        session_count=len(group.session_ids),
        summary=GroupSummaryResponse(**group.summary.model_dump(mode="json")),
        ai_assessment=group.ai_assessment,
        ai_assessment_error=group.ai_assessment_error,
        created_at=group.created_at,
        updated_at=group.updated_at,
        timeline=[
            TimelineEntryResponse(
                timestamp=e.timestamp,
                type=e.type.value,
                title=e.title,
                severity=e.severity,
                data=e.data,
            )
            for e in group.timeline
        ],
    )
```

Also add the needed imports at the top of the file:

```python
from app.modules.impact_analysis.change_group import ChangeGroup
from app.modules.impact_analysis.schemas import (
    # ... existing imports ...
    ChangeGroupListResponse,
    ChangeGroupResponse,
    ChangeGroupDetailResponse,
)
```

- [ ] **Step 2: Add group list endpoint**

Add after the existing session endpoints (before the settings endpoints, around line 556):

```python
# ── Change Group endpoints ────────────────────────────────────────────────


@router.get("/impact-analysis/groups", response_model=ChangeGroupListResponse)
async def list_groups(
    status_filter: str | None = Query(None, alias="status", description="monitoring, partial, completed"),
    severity: str | None = Query(None, description="Filter by worst severity"),
    limit: int = Query(25, ge=1, le=100),
    skip: int = Query(0, ge=0),
    _current_user: User = Depends(require_impact_role),
) -> ChangeGroupListResponse:
    """List change groups with optional filtering."""
    query: dict = {}
    if status_filter:
        query["summary.status"] = status_filter
    if severity:
        query["summary.worst_severity"] = severity

    pipeline: list[dict] = [{"$match": query}, {"$sort": {"created_at": -1}}]
    facet_pipeline = pipeline + [
        {
            "$facet": {
                "total": [{"$count": "n"}],
                "items": [{"$skip": skip}, {"$limit": limit}],
            }
        }
    ]
    results = await ChangeGroup.aggregate(facet_pipeline).to_list()
    row = results[0] if results else {}
    total = row.get("total", [{}])[0].get("n", 0) if row.get("total") else 0
    item_ids = [item["_id"] for item in row.get("items", [])]

    groups = await ChangeGroup.find({"_id": {"$in": item_ids}}).sort("-created_at").to_list()

    return ChangeGroupListResponse(
        groups=[_group_to_response(g) for g in groups],
        total=total,
    )
```

- [ ] **Step 3: Add group detail, sessions, cancel, analyze, and chat endpoints**

```python
@router.get("/impact-analysis/groups/{group_id}", response_model=ChangeGroupDetailResponse)
async def get_group(
    group_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> ChangeGroupDetailResponse:
    """Get a single change group with full detail."""
    group = await ChangeGroup.get(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change group not found")
    return _group_to_detail_response(group)


@router.get("/impact-analysis/groups/{group_id}/sessions", response_model=SessionListResponse)
async def get_group_sessions(
    group_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> SessionListResponse:
    """List all sessions belonging to a change group."""
    group = await ChangeGroup.get(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change group not found")

    sessions = await MonitoringSession.find(
        {"_id": {"$in": group.session_ids}}
    ).sort("-created_at").to_list()

    return SessionListResponse(
        sessions=[_session_to_response(s) for s in sessions],
        total=len(sessions),
    )


@router.post("/impact-analysis/groups/{group_id}/cancel")
async def cancel_group(
    group_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> dict:
    """Cancel all active sessions in a change group."""
    group = await ChangeGroup.get(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change group not found")

    cancelled = 0
    for session_id in group.session_ids:
        result = await session_manager.cancel_session(str(session_id))
        if result:
            cancelled += 1

    return {"cancelled": cancelled, "total": len(group.session_ids)}


@router.post("/impact-analysis/groups/{group_id}/analyze")
async def analyze_group(
    group_id: PydanticObjectId,
    _current_user: User = Depends(require_impact_role),
) -> dict:
    """Trigger or re-trigger AI analysis for a change group."""
    group = await ChangeGroup.get(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change group not found")

    from app.modules.impact_analysis.services.change_group_service import trigger_group_ai_analysis

    create_background_task(
        trigger_group_ai_analysis(str(group.id)),
        name=f"group-ai-reanalyze-{group.id}",
    )
    return {"status": "analysis_triggered"}


@router.post("/impact-analysis/groups/{group_id}/chat", response_model=SessionChatResponse)
async def group_chat(
    group_id: PydanticObjectId,
    body: SessionChatRequest,
    current_user: User = Depends(require_impact_role),
) -> SessionChatResponse:
    """Chat with AI about this change group."""
    group = await ChangeGroup.get(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change group not found")

    context = _build_group_context(group)

    try:
        from app.modules.llm.services.chat_service import handle_chat

        result = await handle_chat(
            feature="impact_group",
            context_ref=str(group.id),
            user_message=body.message,
            user_id=str(current_user.id),
            system_context=context,
            stream_id=body.stream_id,
            mcp_config_ids=body.mcp_config_ids,
            thread_id=group.conversation_thread_id,
        )
        if not group.conversation_thread_id and result.get("thread_id"):
            await ChangeGroup.find_one(ChangeGroup.id == group.id).update(
                {"$set": {"conversation_thread_id": result["thread_id"]}}
            )
        return SessionChatResponse(
            reply=result.get("reply", ""),
            thread_id=result.get("thread_id", ""),
            usage=result.get("usage", {}),
        )
    except ImportError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM service unavailable")


def _build_group_context(group: "ChangeGroup") -> str:
    """Build context string for group-level AI chat."""
    parts = [
        f"Change Group: {group.change_description}",
        f"Source: {group.change_source}",
        f"Triggered by: {group.triggered_by or 'unknown'}",
        f"Devices: {group.summary.total_devices}",
        f"Status: {group.summary.status}",
        f"Worst severity: {group.summary.worst_severity}",
    ]
    if group.summary.devices:
        parts.append("\nDevice Summary:")
        for d in group.summary.devices:
            line = f"  - {d.device_name} ({d.device_type}): {d.status}, severity={d.impact_severity}"
            if d.failed_checks:
                line += f", failed=[{', '.join(d.failed_checks)}]"
            parts.append(line)
    if group.ai_assessment and group.ai_assessment.get("summary"):
        parts.append(f"\nPrevious AI Assessment: {group.ai_assessment['summary'][:500]}")
    return "\n".join(parts)
```

- [ ] **Step 4: Update the summary endpoint to include group counts**

Modify the existing `get_summary` endpoint (around line 356) to include group counts:

```python
@router.get("/impact-analysis/summary", response_model=SessionSummaryResponse)
async def get_summary(
    _current_user: User = Depends(require_impact_role),
) -> SessionSummaryResponse:
    """Get dashboard summary counts."""
    summary = await session_manager.get_session_summary()
    from app.modules.impact_analysis.services.change_group_service import get_group_summary_counts

    group_counts = await get_group_summary_counts()
    return SessionSummaryResponse(**summary, **group_counts)
```

Update `SessionSummaryResponse` in schemas.py to include the new fields:

```python
class SessionSummaryResponse(BaseModel):
    """Dashboard counts for impact analysis sessions."""

    active: int = Field(default=0, description="Sessions currently monitoring")
    impacted: int = Field(default=0, description="Sessions with detected impact")
    completed_24h: int = Field(default=0, description="Sessions completed in the last 24 hours")
    total: int = Field(default=0, description="Total sessions")
    active_groups: int = Field(default=0, description="Active change groups")
    impacted_groups_24h: int = Field(default=0, description="Impacted groups in last 24h")
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/impact_analysis/router.py backend/app/modules/impact_analysis/schemas.py
git commit -m "feat(impact): add ChangeGroup API endpoints and update summary"
```

---

## Task 7: Group-Level AI Analysis

**Files:**
- Modify: `backend/app/modules/impact_analysis/services/analysis_service.py`

- [ ] **Step 1: Add `analyze_change_group` function**

Add at the end of `analysis_service.py`:

```python
async def analyze_change_group(group: "ChangeGroup") -> dict[str, Any]:
    """Run AI analysis for a completed change group using the aggregate summary."""
    from app.modules.impact_analysis.change_group import ChangeGroup

    sanitize_fn = _sanitize_for_prompt

    try:
        llm = await create_llm_service()
    except Exception:
        return _rule_based_group_analysis(group)

    system_prompt = _build_group_system_prompt()
    user_message = _build_group_user_message(group, sanitize_fn)

    try:
        local_mcp = await create_local_mcp_client()
        mcp_clients = [local_mcp] if local_mcp else []
    except Exception:
        mcp_clients = []

    try:
        agent = AIAgentService(llm, mcp_clients=mcp_clients, max_iterations=10)
        result = await agent.run(system_prompt, user_message)

        return {
            "has_impact": group.summary.worst_severity != "none",
            "severity": group.summary.worst_severity,
            "summary": result.get("response", ""),
            "tool_calls": result.get("tool_calls", []),
            "thinking_texts": result.get("thinking_texts", []),
            "source": "ai_agent",
            "trigger": "group_final",
        }
    except Exception as e:
        logger.warning("group_ai_analysis_error", error=str(e))
        return _rule_based_group_analysis(group)


def _build_group_system_prompt() -> str:
    """System prompt for group-level impact analysis."""
    return (
        "You are a network impact analyst for Juniper Mist. A configuration change affected "
        "multiple devices simultaneously. You are given an aggregate summary of all affected "
        "devices including their validation results, SLE metrics, and incidents.\n\n"
        "Your job is to:\n"
        "1. Determine the overall impact of this change across all affected devices\n"
        "2. Identify patterns (e.g., all APs at one site failed the same check)\n"
        "3. Assess whether the impact is isolated or systemic\n"
        "4. Provide concrete recommendations: rollback, adjust settings, or accept\n\n"
        "Be concise and actionable. Focus on cross-device patterns.\n\n"
        "Format your response as:\n"
        "**Severity**: [critical/warning/info]\n"
        "**Summary**: [1-3 sentence summary]\n"
        "**Affected Pattern**: [which devices/types are impacted and why]\n"
        "**Recommendations**:\n"
        "- [recommendation 1]\n"
        "- [recommendation 2]\n\n"
        "You have access to MCP tools for backup, workflow, and system data."
    )


def _build_group_user_message(group: "ChangeGroup", sanitize_fn: Any) -> str:
    """Build the user message with the group aggregate summary."""
    s = group.summary
    parts: list[str] = []

    parts.append(f"## Change: {sanitize_fn(group.change_description)}")
    parts.append(f"- Source: {group.change_source}")
    parts.append(f"- Triggered by: {sanitize_fn(group.triggered_by or 'unknown')}")
    parts.append(f"- Time: {group.triggered_at.isoformat()}")
    parts.append(f"- Total devices: {s.total_devices}")
    parts.append(f"- Status: {s.status}")
    parts.append(f"- Worst severity: {s.worst_severity}")

    # Device type breakdown
    parts.append("\n## Device Type Breakdown")
    for dtype, counts in s.by_type.items():
        parts.append(
            f"- {dtype}: {counts.total} total, {counts.monitoring} monitoring, "
            f"{counts.completed} completed, {counts.impacted} impacted"
        )

    # Per-device table
    parts.append("\n## Per-Device Status")
    parts.append(
        "| Device | Type | Site | Status | Severity | Failed Checks | Incidents | SLE Worst Delta |"
    )
    parts.append(
        "|--------|------|------|--------|----------|---------------|-----------|-----------------|"
    )
    for d in s.devices:
        failed = ", ".join(d.failed_checks) if d.failed_checks else "-"
        incidents_str = "-"
        if d.active_incidents:
            inc_parts = []
            for inc in d.active_incidents[:3]:
                resolved_str = " (resolved)" if inc.resolved else ""
                inc_parts.append(f"{inc.type}{resolved_str}")
            incidents_str = "; ".join(inc_parts)
        sle_str = "-"
        if d.worst_sle_delta:
            sle_str = f"{d.worst_sle_delta.metric} {d.worst_sle_delta.delta_pct:+.1f}%"
        parts.append(
            f"| {sanitize_fn(d.device_name)} | {d.device_type} | {sanitize_fn(d.site_name)} "
            f"| {d.status} | {d.impact_severity} | {failed} | {incidents_str} | {sle_str} |"
        )

    # Validation summary
    if s.validation_summary:
        parts.append("\n## Validation Summary")
        for v in s.validation_summary:
            parts.append(f"- {v.check_name}: {v.passed} passed, {v.failed} failed, {v.skipped} skipped")

    # SLE summary
    if s.sle_summary:
        parts.append("\n## SLE Summary (worst per metric)")
        for metric, delta in s.sle_summary.items():
            parts.append(f"- {metric}: {delta.baseline:.1f} → {delta.current:.1f} ({delta.delta_pct:+.1f}%)")

    return "\n".join(parts)


def _rule_based_group_analysis(group: "ChangeGroup") -> dict[str, Any]:
    """Fallback rule-based analysis for a change group."""
    s = group.summary
    severity = s.worst_severity
    impacted_count = sum(1 for d in s.devices if d.impact_severity != "none")

    parts = []
    if severity == "critical":
        parts.append(f"Critical impact detected on {impacted_count}/{s.total_devices} devices.")
    elif severity == "warning":
        parts.append(f"Warning-level impact detected on {impacted_count}/{s.total_devices} devices.")
    elif severity == "info":
        parts.append(f"Minor observations on {impacted_count}/{s.total_devices} devices.")
    else:
        parts.append(f"No impact detected across {s.total_devices} devices.")

    if s.validation_summary:
        failing = [v for v in s.validation_summary if v.failed > 0]
        if failing:
            names = ", ".join(v.check_name for v in failing[:3])
            parts.append(f"Failing checks: {names}.")

    return {
        "has_impact": severity != "none",
        "severity": severity,
        "summary": " ".join(parts),
        "source": "rule_based",
        "trigger": "group_final",
    }
```

Also add the import at the top of `analysis_service.py`:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.impact_analysis.change_group import ChangeGroup
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/modules/impact_analysis/services/analysis_service.py
git commit -m "feat(impact): add group-level AI analysis with per-device table context"
```

---

## Task 8: Frontend Models & Service

**Files:**
- Modify: `frontend/src/app/features/impact-analysis/models/impact-analysis.model.ts`
- Modify: `frontend/src/app/core/services/impact-analysis.service.ts`

- [ ] **Step 1: Add group TypeScript interfaces**

Append at the end of `frontend/src/app/features/impact-analysis/models/impact-analysis.model.ts`:

```typescript

// ── Change Group models ──────────────────────────────────────────────────

export interface IncidentSummary {
  type: string;
  severity: string;
  timestamp: string;
  resolved: boolean;
}

export interface SLEDeltaSummary {
  metric: string;
  baseline: number;
  current: number;
  delta_pct: number;
}

export interface DeviceSummary {
  session_id: string;
  device_mac: string;
  device_name: string;
  device_type: string;
  site_name: string;
  status: string;
  impact_severity: string;
  failed_checks: string[];
  active_incidents: IncidentSummary[];
  worst_sle_delta: SLEDeltaSummary | null;
}

export interface DeviceTypeCounts {
  total: number;
  monitoring: number;
  completed: number;
  impacted: number;
}

export interface ValidationCheckSummary {
  check_name: string;
  passed: number;
  failed: number;
  skipped: number;
}

export interface GroupSummary {
  total_devices: number;
  by_type: Record<string, DeviceTypeCounts>;
  worst_severity: string;
  validation_summary: ValidationCheckSummary[];
  sle_summary: Record<string, SLEDeltaSummary>;
  devices: DeviceSummary[];
  status: string;
  last_updated: string | null;
}

export interface ChangeGroupResponse {
  id: string;
  audit_id: string;
  org_id: string;
  site_id: string | null;
  change_source: string;
  change_description: string;
  triggered_by: string | null;
  triggered_at: string;
  session_count: number;
  summary: GroupSummary;
  ai_assessment: Record<string, unknown> | null;
  ai_assessment_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChangeGroupDetailResponse extends ChangeGroupResponse {
  timeline: TimelineEntryResponse[];
}

export interface ChangeGroupListResponse {
  groups: ChangeGroupResponse[];
  total: number;
}

export interface SessionSummaryWithGroups extends SessionSummary {
  active_groups: number;
  impacted_groups_24h: number;
}
```

- [ ] **Step 2: Add group API methods to service**

Add the following methods to `ImpactAnalysisService` in `frontend/src/app/core/services/impact-analysis.service.ts`:

```typescript
  // ── Change Groups ──────────────────────────────────────────────────────

  getGroups(params?: {
    status?: string;
    severity?: string;
    limit?: number;
    skip?: number;
  }): Observable<ChangeGroupListResponse> {
    return this.api.get<ChangeGroupListResponse>('/impact-analysis/groups', params);
  }

  getGroup(id: string): Observable<ChangeGroupDetailResponse> {
    return this.api.get<ChangeGroupDetailResponse>(`/impact-analysis/groups/${id}`);
  }

  getGroupSessions(id: string): Observable<SessionListResponse> {
    return this.api.get<SessionListResponse>(`/impact-analysis/groups/${id}/sessions`);
  }

  cancelGroup(id: string): Observable<{ cancelled: number; total: number }> {
    return this.api.post<{ cancelled: number; total: number }>(
      `/impact-analysis/groups/${id}/cancel`,
      {},
    );
  }

  analyzeGroup(id: string): Observable<{ status: string }> {
    return this.api.post<{ status: string }>(`/impact-analysis/groups/${id}/analyze`, {});
  }

  sendGroupChatMessage(
    groupId: string,
    message: string,
    streamId?: string,
    mcpConfigIds?: string[],
  ): Observable<SessionChatResponse> {
    return this.api.post<SessionChatResponse>(
      `/impact-analysis/groups/${groupId}/chat`,
      { message, stream_id: streamId ?? null, mcp_config_ids: mcpConfigIds ?? null },
    );
  }
```

Also add the new imports at the top:

```typescript
import {
  SessionResponse,
  SessionDetailResponse,
  SessionSummary,
  SessionChatResponse,
  ChangeGroupListResponse,
  ChangeGroupDetailResponse,
} from '../../features/impact-analysis/models/impact-analysis.model';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/impact-analysis/models/impact-analysis.model.ts frontend/src/app/core/services/impact-analysis.service.ts
git commit -m "feat(impact): add ChangeGroup frontend models and API service methods"
```

---

## Task 9: Frontend Session List — Show Groups

**Files:**
- Modify: `frontend/src/app/features/impact-analysis/session-list/session-list.component.ts`
- Modify: `frontend/src/app/features/impact-analysis/session-list/session-list.component.html`

- [ ] **Step 1: Add group data loading to the component**

In `session-list.component.ts`, add group state signals and loading alongside sessions:

```typescript
// Add imports
import { ChangeGroupResponse, ChangeGroupListResponse } from '../models/impact-analysis.model';

// Add signals (alongside existing session signals)
groups = signal<ChangeGroupResponse[]>([]);
groupTotal = signal(0);
viewMode = signal<'groups' | 'sessions'>('groups');
```

Add a `loadGroups()` method:

```typescript
loadGroups(): void {
  this.loading.set(true);
  const params: Record<string, string | number> = {
    limit: this.pageSize,
    skip: this.pageIndex * this.pageSize,
  };
  if (this.statusFilter.value) {
    params['status'] = this.statusFilter.value;
  }
  this.impactService.getGroups(params).subscribe({
    next: (res) => {
      this.groups.set(res.groups);
      this.groupTotal.set(res.total);
      this.loading.set(false);
    },
    error: () => this.loading.set(false),
  });
}
```

Update `ngOnInit` to call `loadGroups()` instead of `loadSessions()` by default. Add a toggle method:

```typescript
toggleViewMode(): void {
  this.viewMode.update((m) => (m === 'groups' ? 'sessions' : 'groups'));
  this.pageIndex = 0;
  if (this.viewMode() === 'groups') {
    this.loadGroups();
  } else {
    this.loadSessions();
  }
}
```

Update the WS subscription handler to reload whichever view is active.

Add `viewGroup(group: ChangeGroupResponse)`:

```typescript
viewGroup(group: ChangeGroupResponse): void {
  this.router.navigate(['/impact-analysis/group', group.id]);
}
```

- [ ] **Step 2: Update the template**

In `session-list.component.html`, add a view mode toggle button in the toolbar area:

```html
<button mat-icon-button (click)="toggleViewMode()"
        [matTooltip]="viewMode() === 'groups' ? 'Show individual sessions' : 'Show change groups'">
  <mat-icon>{{ viewMode() === 'groups' ? 'list' : 'layers' }}</mat-icon>
</button>
```

Add a `@switch` block around the table area:

```html
@switch (viewMode()) {
  @case ('groups') {
    <!-- Group table -->
    <table mat-table [dataSource]="groups()">
      <ng-container matColumnDef="worst_severity">
        <th mat-header-cell *matHeaderCellDef>Impact</th>
        <td mat-cell *matCellDef="let g">
          <app-status-badge [status]="g.summary.worst_severity" />
        </td>
      </ng-container>
      <ng-container matColumnDef="change_description">
        <th mat-header-cell *matHeaderCellDef>Change</th>
        <td mat-cell *matCellDef="let g">{{ g.change_description }}</td>
      </ng-container>
      <ng-container matColumnDef="triggered_by">
        <th mat-header-cell *matHeaderCellDef>Triggered By</th>
        <td mat-cell *matCellDef="let g">{{ g.triggered_by || '-' }}</td>
      </ng-container>
      <ng-container matColumnDef="device_count">
        <th mat-header-cell *matHeaderCellDef>Devices</th>
        <td mat-cell *matCellDef="let g">
          @for (entry of g.summary.by_type | keyvalue; track entry.key) {
            <mat-icon class="device-type-icon">{{ deviceTypeIcon(entry.key) }}</mat-icon>
            <span class="device-count">{{ entry.value.total }}</span>
          }
        </td>
      </ng-container>
      <ng-container matColumnDef="status">
        <th mat-header-cell *matHeaderCellDef>Status</th>
        <td mat-cell *matCellDef="let g">{{ g.summary.status }}</td>
      </ng-container>
      <ng-container matColumnDef="created_at">
        <th mat-header-cell *matHeaderCellDef>Detected</th>
        <td mat-cell *matCellDef="let g">{{ g.triggered_at | date: 'short' }}</td>
      </ng-container>
      <tr mat-header-row *matHeaderRowDef="groupColumns"></tr>
      <tr mat-row *matRowDef="let g; columns: groupColumns"
          class="clickable-row" (click)="viewGroup(g)"></tr>
    </table>
    <mat-paginator [length]="groupTotal()" [pageSize]="pageSize"
                   [pageSizeOptions]="[25, 50, 100]" (page)="onGroupPage($event)" />
  }
  @case ('sessions') {
    <!-- Existing session table (unchanged) -->
  }
}
```

Add `groupColumns` to the component:

```typescript
groupColumns = ['worst_severity', 'change_description', 'triggered_by', 'device_count', 'status', 'created_at'];
```

Import `deviceTypeIcon` from `../utils/device-type.utils` and add it as a component method.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/impact-analysis/session-list/
git commit -m "feat(impact): show change groups as primary view in session list"
```

---

## Task 10: Frontend Group Detail Page

**Files:**
- Create: `frontend/src/app/features/impact-analysis/group-detail/group-detail.component.ts`
- Modify: `frontend/src/app/features/impact-analysis/impact-analysis.routes.ts`

- [ ] **Step 1: Create the group detail component**

Create `frontend/src/app/features/impact-analysis/group-detail/group-detail.component.ts`. This is a large component — key sections:

- **Header**: change description, source, triggered by, severity badge, status
- **Summary cards**: total devices, impacted count, active incidents, status
- **Device table**: expandable rows per device with name, type, site, status, severity, failed checks. Click navigates to `/impact-analysis/{session_id}`
- **Validation overview**: aggregated check matrix
- **SLE overview**: per-metric baseline vs current with delta
- **AI assessment panel**: reuse `AiChatPanelComponent` wired to group chat endpoint
- **Timeline**: group-level events

Template structure follows the existing `session-detail.component.ts` pattern with a split chat/data layout.

Key state:

```typescript
group = signal<ChangeGroupDetailResponse | null>(null);
loading = signal(true);
cancelling = signal(false);
llmEnabled = signal(false);

// Computed
isActive = computed(() => {
  const g = this.group();
  return g ? g.summary.status !== 'completed' : false;
});
```

WebSocket subscription to `impact:group:{groupId}` for real-time updates.

The `sendGroupChatMessage` from `ImpactAnalysisService` replaces the per-session chat call.

- [ ] **Step 2: Add route**

In `frontend/src/app/features/impact-analysis/impact-analysis.routes.ts`, add between the existing routes:

```typescript
  {
    path: 'group/:id',
    loadComponent: () =>
      import('./group-detail/group-detail.component').then((m) => m.GroupDetailComponent),
  },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/impact-analysis/group-detail/ frontend/src/app/features/impact-analysis/impact-analysis.routes.ts
git commit -m "feat(impact): add group detail page with device breakdown and AI chat"
```

---

## Task 11: Session Detail Breadcrumb

**Files:**
- Modify: `frontend/src/app/features/impact-analysis/session-detail/session-detail.component.ts`
- Modify: `frontend/src/app/features/impact-analysis/session-detail/session-detail.component.html`

- [ ] **Step 1: Add `change_group_id` to session model**

In `frontend/src/app/features/impact-analysis/models/impact-analysis.model.ts`, add to `SessionResponse`:

```typescript
  change_group_id: string | null;
```

Also add to `SessionDetailResponse` (it inherits, so this is sufficient).

In the backend schema `SessionResponse` in `schemas.py`, add:

```python
    change_group_id: str | None = Field(default=None)
```

In `router.py`, update `_session_to_response` to include:

```python
        change_group_id=str(session.change_group_id) if session.change_group_id else None,
```

- [ ] **Step 2: Add breadcrumb in session detail template**

In `session-detail.component.html`, add a breadcrumb before the back button in the header:

```html
@if (session()?.change_group_id) {
  <a class="breadcrumb-link" [routerLink]="['/impact-analysis/group', session()!.change_group_id]">
    <mat-icon>layers</mat-icon> Change Group
  </a>
  <mat-icon class="breadcrumb-separator">chevron_right</mat-icon>
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/features/impact-analysis/session-detail/ frontend/src/app/features/impact-analysis/models/impact-analysis.model.ts backend/app/modules/impact_analysis/schemas.py backend/app/modules/impact_analysis/router.py
git commit -m "feat(impact): add breadcrumb link from session detail to parent group"
```

---

## Task 12: Update CLAUDE.md Files

**Files:**
- Modify: `backend/app/modules/impact_analysis/CLAUDE.md`
- Modify: `CLAUDE.md` (root)

- [ ] **Step 1: Update impact analysis CLAUDE.md**

Add a "Change Groups" section to `backend/app/modules/impact_analysis/CLAUDE.md`:

```markdown
- **Change Groups** (`change_group.py`, `services/change_group_service.py`): Groups monitoring sessions triggered by the same `audit_id`. `ChangeGroup` document maintains a live `GroupSummary` with per-device status table (recomputed on every child session state change via `_update_group_summary()` in session_manager). AI analysis runs once per group at completion. Use `get_or_create_group(audit_id=...)` — never create ChangeGroup documents directly. WebSocket: `impact:group:{group_id}` for per-group updates.
```

- [ ] **Step 2: Update root CLAUDE.md**

Add a note under the Impact Analysis section mentioning change groups.

- [ ] **Step 3: Commit**

```bash
git add backend/app/modules/impact_analysis/CLAUDE.md CLAUDE.md
git commit -m "docs: update CLAUDE.md files with ChangeGroup architecture"
```

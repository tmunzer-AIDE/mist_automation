"""
Gathers data from other modules to feed LLM prompt builders.

This is the bridge between the LLM module and the rest of the app.
"""

import structlog
from beanie import PydanticObjectId

from app.core.exceptions import DataNotFoundException

logger = structlog.get_logger(__name__)


async def get_backup_diff_context(version_id_1: str, version_id_2: str) -> dict:
    """Fetch two BackupObject versions and compute their diff.

    Returns a dict with:
      - object_type, object_name, event_type
      - old_version, new_version (version numbers)
      - changed_fields (from the newer version)
      - diff_entries (list of {path, type, old?, new?, value?})
    """
    try:
        from app.modules.backup.models import BackupObject
        from app.modules.backup.utils import deep_diff
    except ImportError as e:
        raise DataNotFoundException("Backup module is required for diff context but is not available") from e

    try:
        v1 = await BackupObject.get(PydanticObjectId(version_id_1))
        v2 = await BackupObject.get(PydanticObjectId(version_id_2))
    except Exception as exc:
        raise DataNotFoundException("Invalid version ID format") from exc

    if not v1 or not v2:
        raise DataNotFoundException("One or both backup versions not found")

    # Ensure v1 is the older version
    if v1.version > v2.version:
        v1, v2 = v2, v1

    diff_entries = deep_diff(v1.configuration, v2.configuration)

    return {
        "object_type": v2.object_type,
        "object_name": v2.object_name,
        "object_id": v2.object_id,
        "event_type": v2.event_type.value if hasattr(v2.event_type, "value") else str(v2.event_type),
        "old_version": v1.version,
        "new_version": v2.version,
        "changed_fields": v2.changed_fields,
        "diff_entries": diff_entries,
    }


def get_api_categories() -> list[str]:
    """Return sorted list of API catalog category names."""
    from app.modules.automation.api_catalog import API_CATALOG

    return sorted({entry.category for entry in API_CATALOG})


def get_action_types() -> list[str]:
    """Return all available workflow action types."""
    from app.modules.automation.models.workflow import ActionType

    return [t.value for t in ActionType]


def get_endpoints_for_categories(categories: list[str]) -> str:
    """Return full endpoint details for the given categories.

    Includes method, path, path params, query params, and body info —
    everything the LLM needs to generate correct API node configs.
    """
    from app.modules.automation.api_catalog import API_CATALOG

    cat_set = {c.lower() for c in categories}
    lines: list[str] = []

    for entry in API_CATALOG:
        if entry.category.lower() not in cat_set:
            continue
        parts = [f"{entry.method} {entry.endpoint} — {entry.label}"]
        if entry.path_params:
            parts.append(f"  path_params: {entry.path_params}")
        if entry.query_params:
            qp = [f"{q.name} ({q.type}{'*' if q.required else ''})" for q in entry.query_params]
            parts.append(f"  query_params: {qp}")
        if entry.has_body:
            parts.append("  has_body: true")
        lines.append("\n".join(parts))

    return "\n".join(lines) if lines else "No matching endpoints found."


async def get_debug_context(execution_id: str) -> dict:
    """Fetch execution details for debugging a failed workflow."""
    from app.modules.automation.models.execution import WorkflowExecution

    try:
        execution = await WorkflowExecution.get(PydanticObjectId(execution_id))
    except Exception as exc:
        raise DataNotFoundException("Invalid execution ID") from exc

    if not execution:
        raise DataNotFoundException("Execution not found")

    # Collect failed node details
    failed_nodes = []
    for node_id, result in (execution.node_results or {}).items():
        if result.status == "failed":
            failed_nodes.append({
                "node_id": node_id,
                "node_name": result.node_name,
                "node_type": result.node_type,
                "error": result.error,
                "input_snapshot": result.input_snapshot,
                "retry_count": result.retry_count,
            })

    return {
        "execution_summary": {
            "status": execution.status,
            "duration_ms": execution.duration_ms,
            "nodes_executed": execution.nodes_executed,
            "nodes_succeeded": execution.nodes_succeeded,
            "nodes_failed": execution.nodes_failed,
            "error": execution.error,
        },
        "failed_nodes": failed_nodes,
        "logs": execution.logs or [],
    }


async def get_webhook_summary_context(hours: int = 24, limit: int = 200) -> tuple[str, int]:
    """Fetch recent webhook events and build a condensed summary for the LLM.

    Returns (summary_text, event_count).
    """
    from datetime import datetime, timedelta, timezone

    from app.modules.automation.models.webhook import WebhookEvent

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = await WebhookEvent.find(
        WebhookEvent.received_at >= cutoff,
    ).sort(-WebhookEvent.received_at).limit(limit).to_list()

    if not events:
        return "No webhook events in the specified time range.", 0

    # Group by topic for a concise summary
    by_topic: dict[str, list[str]] = {}
    for evt in events:
        topic = evt.webhook_topic or "unknown"
        entry = by_topic.setdefault(topic, [])
        parts = [evt.event_type or ""]
        if evt.device_name:
            parts.append(f"device={evt.device_name}")
        if evt.site_name:
            parts.append(f"site={evt.site_name}")
        if evt.event_details:
            parts.append(evt.event_details[:80])
        entry.append(" | ".join(p for p in parts if p))

    lines = [f"Total: {len(events)} events in {hours}h\n"]
    for topic, entries in sorted(by_topic.items()):
        lines.append(f"## {topic} ({len(entries)} events)")
        for e in entries[:20]:
            lines.append(f"  - {e}")
        if len(entries) > 20:
            lines.append(f"  ... and {len(entries) - 20} more")

    return "\n".join(lines), len(events)


async def get_dashboard_summary_context() -> str:
    """Gather dashboard stats for LLM summarization."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.modules.automation.models.execution import WorkflowExecution
    from app.modules.automation.models.webhook import WebhookEvent
    from app.modules.automation.models.workflow import Workflow
    from app.modules.backup.models import BackupJob
    from app.modules.impact_analysis.models import MonitoringSession

    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)

    workflow_count, execution_count, failed_execs, webhook_count, backup_count, active_impact, impacted_sessions = (
        await asyncio.gather(
            Workflow.find({"is_active": True}).count(),
            WorkflowExecution.find(WorkflowExecution.started_at >= cutoff_7d).count(),
            WorkflowExecution.find(
                {"started_at": {"$gte": cutoff_7d}, "status": {"$in": ["failed", "timeout"]}}
            ).to_list(),
            WebhookEvent.find(WebhookEvent.received_at >= cutoff_7d).count(),
            BackupJob.find(BackupJob.created_at >= cutoff_7d).count(),
            MonitoringSession.find({"status": {"$in": ["MONITORING", "VALIDATING", "BASELINE_CAPTURE"]}}).count(),
            MonitoringSession.find(
                {"impact_severity": {"$in": ["warning", "critical"]}, "created_at": {"$gte": cutoff_7d}}
            ).count(),
        )
    )

    lines = [
        f"Dashboard overview (last 7 days, as of {now.strftime('%Y-%m-%d %H:%M UTC')}):",
        f"- Active workflows: {workflow_count}",
        f"- Executions: {execution_count} total, {len(failed_execs)} failed/timeout",
        f"- Webhook events: {webhook_count}",
        f"- Backup jobs: {backup_count}",
        f"- Impact analysis: {active_impact} active sessions, {impacted_sessions} with impact",
    ]

    if failed_execs:
        lines.append("\nFailed/timeout executions:")
        for ex in failed_execs[:10]:
            wf_name = getattr(ex, "workflow_name", None) or "unknown"
            started = ex.started_at.strftime("%Y-%m-%d %H:%M") if ex.started_at else "?"
            lines.append(f"  - Workflow: {wf_name}, status: {ex.status}, started: {started}")

    return "\n".join(lines)


async def get_audit_log_summary_context(
    event_type: str | None = None,
    user_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 500,
) -> tuple[str, int]:
    """Fetch audit logs matching filters for LLM summarization."""
    from datetime import datetime, timedelta, timezone

    from app.models.system import AuditLog

    query: dict = {}
    if event_type:
        query["event_type"] = event_type
    if user_id:
        query["user_id"] = user_id
    if start_date:
        query.setdefault("timestamp", {})["$gte"] = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if end_date:
        query.setdefault("timestamp", {})["$lte"] = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

    if not query:
        query["timestamp"] = {"$gte": datetime.now(timezone.utc) - timedelta(hours=24)}

    logs = await AuditLog.find(query).sort("-timestamp").limit(limit).to_list()

    if not logs:
        return "No audit log entries matching the specified filters.", 0

    lines = [f"Total: {len(logs)} audit log entries\n"]
    for log in logs:
        ts = log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "?"
        success = "OK" if log.success else "FAILED"
        lines.append(
            f"- [{ts}] {log.event_type} ({success}) "
            f"user={log.user_email or '?'} target={log.target_type or ''}:{log.target_name or ''} "
            f"— {log.description[:100]}"
        )

    return "\n".join(lines), len(logs)


async def get_system_log_summary_context(
    level: str | None = None,
    logger: str | None = None,
    limit: int = 500,
) -> tuple[str, int]:
    """Fetch system logs from ring buffer for LLM summarization."""
    from app.core.log_broadcaster import get_recent_logs

    all_logs = get_recent_logs(limit)

    logs = all_logs
    if level:
        logs = [entry for entry in logs if entry.get("level", "").lower() == level.lower()]
    if logger:
        logs = [entry for entry in logs if entry.get("logger", "") == logger]

    if not logs:
        return "No system log entries matching the specified filters.", 0

    lines = [f"Total: {len(logs)} system log entries\n"]
    for log in logs[:200]:
        ts = log.get("timestamp", "?")
        lvl = log.get("level", "?")
        event = str(log.get("event", "?"))[:120]
        lgr = log.get("logger", "?")
        lines.append(f"- [{ts}] [{lvl}] {lgr}: {event}")

    if len(logs) > 200:
        lines.append(f"... and {len(logs) - 200} more entries")

    return "\n".join(lines), len(logs)


async def get_backup_summary_context(
    object_type: str | None = None,
    site_id: str | None = None,
    scope: str | None = None,
) -> tuple[str, int]:
    """Gather backup health and change activity for LLM summarization."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.modules.backup.models import BackupJob, BackupObject

    now = datetime.now(timezone.utc)
    cutoff_7d = now - timedelta(days=7)

    obj_query: dict = {}
    if object_type:
        obj_query["object_type"] = object_type
    if site_id:
        obj_query["site_id"] = site_id
    if scope == "org":
        obj_query["site_id"] = None
    elif scope == "site":
        obj_query["site_id"] = {"$ne": None}

    job_query: dict = {"created_at": {"$gte": cutoff_7d}}

    objects, recent_jobs, failed_jobs = await asyncio.gather(
        BackupObject.find(obj_query).sort("-backed_up_at").limit(500).to_list(),
        BackupJob.find(job_query).count(),
        BackupJob.find({**job_query, "status": "failed"}).count(),
    )

    if not objects:
        return "No backup objects matching the specified filters.", 0

    stale = [o for o in objects if o.backed_up_at and o.backed_up_at < cutoff_7d]

    by_type: dict[str, int] = {}
    for o in objects:
        by_type[o.object_type] = by_type.get(o.object_type, 0) + 1

    lines = [
        f"Backup overview (as of {now.strftime('%Y-%m-%d %H:%M UTC')}):",
        f"- Total objects: {len(objects)}",
        f"- By type: {', '.join(f'{t}: {c}' for t, c in sorted(by_type.items()))}",
        f"- Stale (>7 days since last backup): {len(stale)}",
        f"- Recent jobs (7d): {recent_jobs} total, {failed_jobs} failed",
    ]

    if stale:
        lines.append("\nStale objects:")
        for o in stale[:20]:
            age = (now - o.backed_up_at).days if o.backed_up_at else "never"
            lines.append(f"  - {o.object_type}/{o.object_name or o.object_id} — {age} days old")

    changed = [o for o in objects if o.backed_up_at and o.backed_up_at >= cutoff_7d and o.version > 1]
    if changed:
        lines.append(f"\nRecently changed objects ({len(changed)}):")
        for o in changed[:20]:
            fields = ", ".join(o.changed_fields[:5]) if o.changed_fields else "N/A"
            lines.append(f"  - {o.object_type}/{o.object_name or o.object_id} v{o.version} — fields: {fields}")

    return "\n".join(lines), len(objects)

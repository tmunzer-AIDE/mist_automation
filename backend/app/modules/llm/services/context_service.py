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

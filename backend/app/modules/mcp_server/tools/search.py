"""
Universal search tool — single entry point for discovering data across all domains.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from beanie import Document
from pydantic import Field

from app.modules.mcp_server.helpers import to_json
from app.modules.mcp_server.server import mcp


async def _paginated_query(
    model: type[Document], pipeline: list[dict[str, Any]], skip: int, limit: int
) -> tuple[int, list[dict]]:
    """Run a MongoDB aggregation with $facet pagination and return (total, items)."""
    faceted = pipeline + [
        {"$facet": {"total": [{"$count": "n"}], "items": [{"$skip": skip}, {"$limit": limit}]}}
    ]
    results = await model.aggregate(faceted).to_list()
    row = results[0] if results else {}
    total = row.get("total", [{}])[0].get("n", 0) if row.get("total") else 0
    return total, row.get("items", [])


@mcp.tool()
async def search(
    type: Annotated[
        str,
        Field(
            description=(
                "What to search for. "
                "One of: 'backup_objects' (Mist config snapshots), 'workflows' (automation workflows), "
                "'executions' (workflow execution history), 'webhook_events' (received Mist webhooks), "
                "'reports' (post-deployment validation reports)."
            ),
        ),
    ],
    query: Annotated[
        str,
        Field(
            description="Text to search for — matches against name, type, or ID (case-insensitive substring).",
        ),
    ] = "",
    object_type: Annotated[
        str,
        Field(
            description=(
                "Filter backup objects by Mist object type (e.g. 'wlans', 'networks', 'devices', 'sites'). "
                "Only used when type='backup_objects'."
            ),
        ),
    ] = "",
    site_id: Annotated[
        str,
        Field(description="Filter by Mist site UUID. Applies to backup_objects, webhook_events, and reports."),
    ] = "",
    status: Annotated[
        str,
        Field(
            description=(
                "Filter by status. Values depend on type: "
                "backup_objects: 'active'|'deleted'; "
                "workflows: 'enabled'|'disabled'|'draft'; "
                "executions: 'success'|'failed'|'running'|'timeout'; "
                "reports: 'completed'|'failed'|'pending'|'running'."
            ),
        ),
    ] = "",
    event_type: Annotated[
        str,
        Field(description="Filter webhook events by event type (e.g. 'AP_CONNECTED'). Only for type='webhook_events'."),
    ] = "",
    hours: Annotated[
        int,
        Field(description="Time window in hours. Filters webhook_events by received_at (default 24h if omitted). Set 0 to disable.", ge=0),
    ] = 0,
    skip: Annotated[int, Field(description="Number of results to skip for pagination.", ge=0)] = 0,
    limit: Annotated[int, Field(description="Max results to return (1-25).", ge=1, le=25)] = 10,
) -> str:
    """Search across the platform: find backup objects, workflows, executions, webhook events, or reports.

    Returns a compact list of matching items with id, name, type, status, summary, and date.
    Use the 'backup', 'workflow', or 'get_details' tools to get full details for a specific item.
    """
    limit = min(limit, 25)

    dispatchers = {
        "backup_objects": _search_backup_objects,
        "workflows": _search_workflows,
        "executions": _search_executions,
        "webhook_events": _search_webhook_events,
        "reports": _search_reports,
    }

    handler = dispatchers.get(type)
    if not handler:
        return to_json({"error": f"Unknown type '{type}'. Use: {', '.join(dispatchers)}"})

    return await handler(
        query=query,
        object_type=object_type,
        site_id=site_id,
        status=status,
        event_type=event_type,
        hours=hours,
        skip=skip,
        limit=limit,
    )


async def _search_backup_objects(*, query: str, object_type: str, site_id: str, status: str, **_kwargs) -> str:
    from app.modules.backup.models import BackupObject

    match: dict = {}
    if object_type:
        match["object_type"] = object_type
    if site_id:
        match["site_id"] = site_id
    if status == "deleted":
        match["is_deleted"] = True
    elif status == "active":
        match["is_deleted"] = False
    if query:
        match["$or"] = [
            {"object_name": {"$regex": re.escape(query), "$options": "i"}},
            {"object_type": {"$regex": re.escape(query), "$options": "i"}},
            {"object_id": {"$regex": re.escape(query), "$options": "i"}},
        ]

    skip = _kwargs.get("skip", 0)
    limit = _kwargs.get("limit", 10)

    pipeline = [
        {"$match": match},
        {"$sort": {"version": -1}},
        {
            "$group": {
                "_id": "$object_id",
                "object_type": {"$first": "$object_type"},
                "object_name": {"$first": "$object_name"},
                "site_id": {"$first": "$site_id"},
                "is_deleted": {"$first": "$is_deleted"},
                "version_count": {"$sum": 1},
                "latest_version": {"$first": "$version"},
                "last_backed_up_at": {"$first": "$backed_up_at"},
            }
        },
        {"$sort": {"last_backed_up_at": -1}},
    ]

    total, items = await _paginated_query(BackupObject, pipeline, skip, limit)

    return to_json(
        {
            "results": [
                {
                    "id": item["_id"],
                    "name": item.get("object_name", ""),
                    "type": item.get("object_type", ""),
                    "status": "deleted" if item.get("is_deleted") else "active",
                    "summary": f"v{item.get('latest_version', 0)}, {item.get('version_count', 0)} versions",
                    "date": item.get("last_backed_up_at"),
                }
                for item in items
            ],
            "total": total,
        }
    )


async def _search_workflows(*, query: str, status: str, **_kwargs) -> str:
    from app.modules.automation.models.workflow import Workflow

    match: dict = {}
    if status:
        match["status"] = status
    if query:
        match["name"] = {"$regex": re.escape(query), "$options": "i"}

    skip = _kwargs.get("skip", 0)
    limit = _kwargs.get("limit", 10)

    pipeline = [{"$match": match}, {"$sort": {"updated_at": -1}}]
    total, items = await _paginated_query(Workflow, pipeline, skip, limit)

    return to_json(
        {
            "results": [
                {
                    "id": str(item["_id"]),
                    "name": item.get("name", ""),
                    "type": item.get("workflow_type", "standard"),
                    "status": item.get("status", ""),
                    "summary": f"{len(item.get('nodes', []))} nodes, {item.get('execution_count', 0)} runs",
                    "date": item.get("updated_at"),
                }
                for item in items
            ],
            "total": total,
        }
    )


async def _search_executions(*, query: str, status: str, hours: int, **_kwargs) -> str:
    from app.modules.automation.models.execution import WorkflowExecution

    match: dict = {"is_simulation": False}
    if status:
        match["status"] = status
    if query:
        match["workflow_name"] = {"$regex": re.escape(query), "$options": "i"}
    if hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        match["started_at"] = {"$gte": cutoff}

    skip = _kwargs.get("skip", 0)
    limit = _kwargs.get("limit", 10)

    pipeline = [{"$match": match}, {"$sort": {"started_at": -1}}]
    total, items = await _paginated_query(WorkflowExecution, pipeline, skip, limit)

    return to_json(
        {
            "results": [
                {
                    "id": str(item["_id"]),
                    "name": item.get("workflow_name", ""),
                    "type": item.get("trigger_type", ""),
                    "status": item.get("status", ""),
                    "summary": f"{item.get('nodes_executed', 0)} nodes, {item.get('duration_ms', 0)}ms",
                    "date": item.get("started_at"),
                }
                for item in items
            ],
            "total": total,
        }
    )


async def _search_webhook_events(*, query: str, site_id: str, event_type: str, hours: int, **_kwargs) -> str:
    from app.modules.automation.models.webhook import WebhookEvent

    match: dict = {}
    if site_id:
        match["site_id"] = site_id
    if event_type:
        match["event_type"] = event_type
    if query:
        match["$or"] = [
            {"event_type": {"$regex": re.escape(query), "$options": "i"}},
            {"device_name": {"$regex": re.escape(query), "$options": "i"}},
            {"site_name": {"$regex": re.escape(query), "$options": "i"}},
        ]
    cutoff_hours = hours if hours > 0 else 24
    match["received_at"] = {"$gte": datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)}

    skip = _kwargs.get("skip", 0)
    limit = _kwargs.get("limit", 10)

    pipeline = [{"$match": match}, {"$sort": {"received_at": -1}}]
    total, items = await _paginated_query(WebhookEvent, pipeline, skip, limit)

    return to_json(
        {
            "results": [
                {
                    "id": str(item["_id"]),
                    "name": item.get("device_name", item.get("event_type", "")),
                    "type": item.get("webhook_topic", ""),
                    "status": "processed" if item.get("processed") else "pending",
                    "summary": f"{item.get('event_type', '')} at {item.get('site_name', '')}",
                    "date": item.get("received_at"),
                }
                for item in items
            ],
            "total": total,
        }
    )


async def _search_reports(*, query: str, site_id: str, status: str, **_kwargs) -> str:
    from app.modules.reports.models import ReportJob

    match: dict = {}
    if site_id:
        match["site_id"] = site_id
    if status:
        match["status"] = status
    if query:
        match["site_name"] = {"$regex": re.escape(query), "$options": "i"}

    skip = _kwargs.get("skip", 0)
    limit = _kwargs.get("limit", 10)

    pipeline = [{"$match": match}, {"$sort": {"created_at": -1}}]
    total, items = await _paginated_query(ReportJob, pipeline, skip, limit)

    return to_json(
        {
            "results": [
                {
                    "id": str(item["_id"]),
                    "name": item.get("site_name", ""),
                    "type": item.get("report_type", ""),
                    "status": item.get("status", ""),
                    "summary": f"Site: {item.get('site_name', 'unknown')}",
                    "date": item.get("created_at"),
                }
                for item in items
            ],
            "total": total,
        }
    )

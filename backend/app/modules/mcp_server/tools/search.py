"""
Universal search tool — single entry point for discovering data across all domains.
"""

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from beanie import Document
from fastmcp.exceptions import ToolError
from pydantic import Field

from app.modules.mcp_server.helpers import to_json
from app.modules.mcp_server.server import mcp
from app.modules.mcp_server.tools.utils import is_placeholder, is_uuid

# Per-type mapping from generic sort names to MongoDB field names.
_SORT_FIELDS: dict[str, dict[str, str]] = {
    "backup_objects": {
        "name": "object_name",
        "date": "last_modified_at",
        "status": "is_deleted",
        "type": "object_type",
    },
    "backup_jobs": {
        "name": "org_name",
        "date": "created_at",
        "status": "status",
        "type": "backup_type",
    },
    "workflows": {
        "name": "name",
        "date": "updated_at",
        "status": "status",
        "type": "workflow_type",
    },
    "executions": {
        "name": "workflow_name",
        "date": "started_at",
        "status": "status",
        "type": "trigger_type",
    },
    "webhook_events": {
        "name": "device_name",
        "date": "received_at",
        "status": "processed",
        "type": "webhook_topic",
    },
    "reports": {
        "name": "site_name",
        "date": "created_at",
        "status": "status",
        "type": "report_type",
    },
}

_SEARCH_TYPES: set[str] = {
    "backup_objects",
    "backup_jobs",
    "workflows",
    "executions",
    "webhook_events",
    "reports",
}

_SORT_BY_VALUES: set[str] = {"name", "date", "status", "type"}
_SORT_ORDER_VALUES: set[str] = {"asc", "desc"}

_SITE_ID_SUPPORTED_TYPES: set[str] = {"backup_objects", "webhook_events", "reports"}
_EVENT_TYPE_SUPPORTED_TYPES: set[str] = {"webhook_events"}
_HOURS_SUPPORTED_TYPES: set[str] = {"backup_jobs", "executions", "webhook_events"}

_STATUS_VALUES: dict[str, set[str]] = {
    "backup_objects": {"active", "deleted"},
    "backup_jobs": {"pending", "in_progress", "completed", "failed", "cancelled"},
    "workflows": {"enabled", "disabled", "draft"},
    "executions": {"success", "failed", "running", "timeout"},
    "reports": {"completed", "failed", "pending", "running"},
}

_OBJECT_TYPE_ALIASES: dict[str, str] = {
    "site": "sites",
    "setting": "settings",
    "site_setting": "settings",
    "network": "networks",
    "wlan": "wlans",
    "device": "devices",
}


def _normalize_backup_object_type(value: str) -> str:
    key = value.strip().lower()
    return _OBJECT_TYPE_ALIASES.get(key, key)


def _valid_backup_object_types() -> set[str]:
    """Return valid backup object_type keys from the object registry."""
    from app.modules.backup.object_registry import ORG_OBJECTS, SITE_OBJECTS

    return set(ORG_OBJECTS.keys()) | set(SITE_OBJECTS.keys())


def _validate_search_inputs(
    *,
    search_type: str,
    query: str,
    object_type: str,
    site_id: str,
    status: str,
    event_type: str,
    hours: int,
    skip: int,
    limit: int,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    """Validate and normalize cross-field search inputs.

    Raises ToolError when inputs are invalid or incoherent.
    """
    stype = search_type.strip().lower()
    if stype not in _SEARCH_TYPES:
        raise ToolError(f"Unknown search_type '{search_type}'. Use: {', '.join(sorted(_SEARCH_TYPES))}")

    sby = sort_by.strip().lower()
    if sby not in _SORT_BY_VALUES:
        raise ToolError(f"Invalid sort_by '{sort_by}'. Use: {', '.join(sorted(_SORT_BY_VALUES))}")

    sorder = sort_order.strip().lower()
    if sorder not in _SORT_ORDER_VALUES:
        raise ToolError(f"Invalid sort_order '{sort_order}'. Use: asc or desc")

    if skip < 0:
        raise ToolError("skip must be >= 0")
    if limit < 1 or limit > 25:
        raise ToolError("limit must be between 1 and 25")
    if hours < 0:
        raise ToolError("hours must be >= 0")

    q = query.strip()
    if q and is_placeholder(q):
        raise ToolError(
            f"Invalid query '{query}': unresolved placeholders are not allowed in search input."
        )

    sid = site_id.strip()
    if sid:
        if stype not in _SITE_ID_SUPPORTED_TYPES:
            raise ToolError(
                f"site_id is not supported for search_type='{stype}'. Supported types: "
                f"{', '.join(sorted(_SITE_ID_SUPPORTED_TYPES))}"
            )
        if is_placeholder(sid):
            raise ToolError(
                f"Invalid site_id '{site_id}': unresolved placeholders are not allowed."
            )
        if not is_uuid(sid):
            raise ToolError(
                f"Invalid site_id '{site_id}'. site_id must be a real UUID."
            )

    otype = object_type.strip()
    normalized_object_type = ""
    if otype:
        if stype != "backup_objects":
            raise ToolError("object_type is only supported when search_type='backup_objects'")
        if is_placeholder(otype):
            raise ToolError(
                f"Invalid object_type '{object_type}': unresolved placeholders are not allowed."
            )
        normalized_object_type = _normalize_backup_object_type(otype)
        valid_types = _valid_backup_object_types()
        if normalized_object_type not in valid_types:
            raise ToolError(
                f"Unknown backup object_type '{object_type}'. "
                f"Use a valid Mist object type such as sites, info, settings, wlans, networks, devices."
            )

    if stype == "backup_objects" and not normalized_object_type and not sid:
        raise ToolError(
            "For search_type='backup_objects', provide object_type or site_id to keep the query coherent. "
            "To find a site by name, use object_type='sites' (or 'info') with query='<site-name>'."
        )

    etype = event_type.strip()
    if etype and stype not in _EVENT_TYPE_SUPPORTED_TYPES:
        raise ToolError("event_type is only supported when search_type='webhook_events'")

    normalized_hours = hours
    if stype not in _HOURS_SUPPORTED_TYPES:
        # Tolerate the default (0) and legacy callers passing 24, but reject any other value.
        if hours not in (0, 24):
            raise ToolError(
                f"hours is not supported for search_type='{stype}'. Supported types: "
                f"{', '.join(sorted(_HOURS_SUPPORTED_TYPES))}"
            )
        normalized_hours = 0

    sstatus = status.strip().lower()
    if sstatus:
        allowed_status = _STATUS_VALUES.get(stype)
        if not allowed_status:
            raise ToolError(f"status is not supported for search_type='{stype}'")
        if sstatus not in allowed_status:
            raise ToolError(
                f"Invalid status '{status}' for search_type='{stype}'. "
                f"Allowed: {', '.join(sorted(allowed_status))}"
            )

    return {
        "search_type": stype,
        "query": q,
        "object_type": normalized_object_type,
        "site_id": sid,
        "status": sstatus,
        "event_type": etype,
        "hours": normalized_hours,
        "skip": skip,
        "limit": limit,
        "sort_by": sby,
        "sort_order": sorder,
    }


def _resolve_sort(search_type: str, sort_by: str, sort_order: str) -> dict[str, int]:
    """Resolve generic sort params to a MongoDB $sort dict."""
    fields = _SORT_FIELDS.get(search_type, {})
    field = fields.get(sort_by, fields.get("date", "created_at"))
    direction = 1 if sort_order == "asc" else -1
    return {field: direction}


async def _paginated_query(
    model: type[Document], pipeline: list[dict[str, Any]], skip: int, limit: int
) -> tuple[int, list[dict]]:
    """Run a MongoDB aggregation with $facet pagination and return (total, items)."""
    faceted = pipeline + [{"$facet": {"total": [{"$count": "n"}], "items": [{"$skip": skip}, {"$limit": limit}]}}]
    results = await model.aggregate(faceted).to_list()
    row = results[0] if results else {}
    total = row.get("total", [{}])[0].get("n", 0) if row.get("total") else 0
    return total, row.get("items", [])


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
async def search(
    search_type: Annotated[
        str,
        Field(
            description=(
                "What to search for. One of:\n"
                "- 'backup_objects': Mist config snapshots (versioned). Requires object_type or site_id.\n"
                "- 'backup_jobs': backup run history with status/type/date filters.\n"
                "- 'workflows': automation workflow definitions.\n"
                "- 'executions': workflow execution history.\n"
                "- 'webhook_events': received Mist webhook events (last 24h by default).\n"
                "- 'reports': post-deployment validation reports.\n"
                "To look up a site by name, call with search_type='backup_objects', "
                "object_type='sites' (or 'info'), query='<site-name>'."
            ),
        ),
    ],
    query: Annotated[
        str,
        Field(
            description=(
                "Text to search for (case-insensitive substring). "
                "For search_type='backup_objects', matches object name, object type, object ID, and configuration.name. "
                "To find a site by name, combine with object_type='sites' (or 'info')."
            ),
        ),
    ] = "",
    object_type: Annotated[
        str,
        Field(
            description=(
                "Filter backup objects by Mist object type (e.g. 'sites', 'info', 'settings', 'wlans', 'networks', 'devices'). "
                "ONLY valid when search_type='backup_objects'. "
                "For coherent site-name lookup, set object_type to 'sites' or 'info'."
            ),
        ),
    ] = "",
    site_id: Annotated[
        str,
        Field(
            description=(
                "Filter by Mist site UUID (must be a real UUID, not a name). "
                "Applies to search_type='backup_objects', 'webhook_events', and 'reports' only."
            )
        ),
    ] = "",
    status: Annotated[
        str,
        Field(
            description=(
                "Filter by status. Valid values depend on search_type:\n"
                "- backup_objects: 'active' | 'deleted'\n"
                "- backup_jobs: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled'\n"
                "- workflows: 'enabled' | 'disabled' | 'draft'\n"
                "- executions: 'success' | 'failed' | 'running' | 'timeout'\n"
                "- reports: 'completed' | 'failed' | 'pending' | 'running'\n"
                "Not supported for webhook_events."
            ),
        ),
    ] = "",
    event_type: Annotated[
        str,
        Field(
            description=(
                "Filter webhook events by event type (e.g. 'AP_CONNECTED', 'SW_CONFIGURED'). "
                "ONLY valid when search_type='webhook_events'."
            )
        ),
    ] = "",
    hours: Annotated[
        int,
        Field(
            description=(
                "Time window in hours. Only supported when search_type is one of: "
                "'backup_jobs', 'executions', 'webhook_events'. "
                "Default 0 means no filter for backup_jobs/executions, and 24h for webhook_events. "
                "Set >0 to filter to events within the last N hours."
            ),
            ge=0,
        ),
    ] = 0,
    skip: Annotated[int, Field(description="Number of results to skip for pagination (0-based offset).", ge=0)] = 0,
    limit: Annotated[int, Field(description="Max results to return (1-25).", ge=1, le=25)] = 10,
    sort_by: Annotated[
        str,
        Field(
            description=(
                "Field to sort results by. One of: 'name', 'date', 'status', 'type'. "
                "Default: 'date'. Example: sort_by='date', sort_order='desc' for most recent first."
            ),
        ),
    ] = "date",
    sort_order: Annotated[
        str,
        Field(
            description=(
                "Sort direction: 'asc' (ascending) or 'desc' (descending). Default: 'desc'. "
                "Example: sort_by='name', sort_order='asc' for alphabetical."
            )
        ),
    ] = "desc",
) -> str:
    """Discover items across the platform: backup objects, workflows, executions, webhook events, or reports.

    Returns a compact list with id, name, type, status, summary, and date per match.

    Typical workflow (read-only):
    - To inspect a webhook_event or report: pass the result id to get_details.
    - To inspect a backup version history: pass the object_id to backup(action='object_info').
    - To inspect a workflow definition: pass the workflow_id to workflow(action='detail').
    - To inspect an execution: pass the execution_id to workflow(action='execution_detail').

    This tool is read-only. It does NOT modify Mist configuration or trigger any side effects.
    """
    validated = _validate_search_inputs(
        search_type=search_type,
        query=query,
        object_type=object_type,
        site_id=site_id,
        status=status,
        event_type=event_type,
        hours=hours,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    dispatchers = {
        "backup_objects": _search_backup_objects,
        "backup_jobs": _search_backup_jobs,
        "workflows": _search_workflows,
        "executions": _search_executions,
        "webhook_events": _search_webhook_events,
        "reports": _search_reports,
    }

    search_type = validated["search_type"]
    handler = dispatchers[search_type]

    sort = _resolve_sort(search_type, validated["sort_by"], validated["sort_order"])

    return await handler(
        query=validated["query"],
        object_type=validated["object_type"],
        site_id=validated["site_id"],
        status=validated["status"],
        event_type=validated["event_type"],
        hours=validated["hours"],
        skip=validated["skip"],
        limit=validated["limit"],
        sort=sort,
    )


async def _search_backup_jobs(*, query: str, status: str, hours: int, sort: dict[str, int], **_kwargs) -> str:
    from app.modules.backup.models import BackupJob

    match: dict = {}
    if status:
        match["status"] = status
    if query:
        match["$or"] = [
            {"org_name": {"$regex": re.escape(query), "$options": "i"}},
            {"backup_type": {"$regex": re.escape(query), "$options": "i"}},
        ]
    if hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        match["created_at"] = {"$gte": cutoff}

    skip = _kwargs.get("skip", 0)
    limit = _kwargs.get("limit", 10)
    pipeline = [{"$match": match}, {"$sort": sort}]
    total, items = await _paginated_query(BackupJob, pipeline, skip, limit)

    return to_json(
        {
            "results": [
                {
                    "id": str(item["_id"]),
                    "name": item.get("org_name", item.get("org_id", "")),
                    "type": item.get("backup_type", ""),
                    "status": item.get("status", ""),
                    "summary": f"{item.get('object_count', 0)} objects"
                    + (f", error: {item['error']}" if item.get("error") else ""),
                    "date": item.get("created_at"),
                }
                for item in items
            ],
            "total": total,
        }
    )


def _collect_duplicate_names(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group results that share a non-empty `name`, returning only the name-collisions.

    Returns a dict mapping each colliding name to the list of {id, status, summary, date}
    entries from the search results. Empty when all names are unique.
    """
    name_counts: Counter[str] = Counter()
    for r in results:
        name = r.get("name")
        if isinstance(name, str) and name:
            name_counts[name] += 1
    duplicate_names = {name for name, count in name_counts.items() if count > 1}
    if not duplicate_names:
        return {}
    return {
        name: [
            {
                "id": r["id"],
                "status": r.get("status", ""),
                "summary": r.get("summary", ""),
                "date": r.get("date"),
            }
            for r in results
            if r.get("name") == name
        ]
        for name in duplicate_names
    }


async def _search_backup_objects(
    *, query: str, object_type: str, site_id: str, status: str, sort: dict[str, int], **_kwargs
) -> str:
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
            {"configuration.name": {"$regex": re.escape(query), "$options": "i"}},
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
                "org_id": {"$first": "$org_id"},
                "site_id": {"$first": "$site_id"},
                "is_deleted": {"$first": "$is_deleted"},
                "version_count": {"$sum": 1},
                "latest_version": {"$first": "$version"},
                "last_modified_at": {"$first": "$last_modified_at"},
                "config_name": {"$first": "$configuration.name"},
            }
        },
        {"$sort": sort},
    ]

    total, items = await _paginated_query(BackupObject, pipeline, skip, limit)

    results = [
        {
            "id": item["_id"],
            "name": item.get("object_name") or item.get("config_name", ""),
            "type": item.get("object_type", ""),
            "status": "deleted" if item.get("is_deleted") else "active",
            "summary": f"v{item.get('latest_version', 0)}, {item.get('version_count', 0)} versions",
            "date": item.get("last_modified_at"),
            "org_id": item.get("org_id"),
            "site_id": item.get("site_id"),
        }
        for item in items
    ]

    response: dict[str, Any] = {"results": results, "total": total}
    duplicates = _collect_duplicate_names(results)
    if duplicates:
        response["duplicate_names"] = duplicates
        response["disambiguation_hint"] = (
            "Multiple results share the same name. Use the object_id from duplicate_names to pick "
            "the correct object — the entry with the most recent date and highest version count is "
            "usually the live object."
        )
    return to_json(response)


async def _search_workflows(*, query: str, status: str, sort: dict[str, int], **_kwargs) -> str:
    from app.modules.automation.models.workflow import Workflow

    match: dict = {}
    if status:
        match["status"] = status
    if query:
        match["name"] = {"$regex": re.escape(query), "$options": "i"}

    skip = _kwargs.get("skip", 0)
    limit = _kwargs.get("limit", 10)

    pipeline = [{"$match": match}, {"$sort": sort}]
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


async def _search_executions(*, query: str, status: str, hours: int, sort: dict[str, int], **_kwargs) -> str:
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

    pipeline = [{"$match": match}, {"$sort": sort}]
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


async def _search_webhook_events(
    *, query: str, site_id: str, event_type: str, hours: int, sort: dict[str, int], **_kwargs
) -> str:
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

    pipeline = [{"$match": match}, {"$sort": sort}]
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


async def _search_reports(*, query: str, site_id: str, status: str, sort: dict[str, int], **_kwargs) -> str:
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

    pipeline = [{"$match": match}, {"$sort": sort}]
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

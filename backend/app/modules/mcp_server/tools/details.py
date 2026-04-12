"""
Details tool — get details for webhook events, reports, or dashboard.

Types: webhook_event, report, dashboard.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from app.modules.mcp_server.helpers import cap_list, to_json, truncate_value
from app.modules.mcp_server.server import mcp
from app.modules.mcp_server.tools.utils import is_placeholder

_DETAIL_TYPES: set[str] = {"webhook_event", "report", "dashboard"}
_REPORT_SECTIONS: set[str] = {"aps", "switches", "gateways", "template_variables"}


def _validate_details_inputs(*, detail_type: str, id_value: str, section: str) -> dict[str, str]:
    dtype = detail_type.strip().lower()
    if dtype not in _DETAIL_TYPES:
        raise ToolError(f"Unknown type '{detail_type}'. Use: {', '.join(sorted(_DETAIL_TYPES))}")

    item_id = id_value.strip()
    if item_id and is_placeholder(item_id):
        raise ToolError(f"Invalid id '{id_value}': unresolved placeholders are not allowed")

    section_name = section.strip().lower()
    if section_name and dtype != "report":
        raise ToolError("section is only supported when type='report'")

    if dtype in {"webhook_event", "report"} and not item_id:
        raise ToolError(f"id is required for type='{dtype}'")

    if dtype == "dashboard":
        if item_id:
            raise ToolError("id is not supported when type='dashboard'")
        if section_name:
            raise ToolError("section is not supported when type='dashboard'")

    if section_name and section_name not in _REPORT_SECTIONS:
        raise ToolError(
            f"Invalid section '{section}'. Use: {', '.join(sorted(_REPORT_SECTIONS))}"
        )

    return {"type": dtype, "id": item_id, "section": section_name}


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
async def get_details(
    type: Annotated[
        str,
        Field(
            description=(
                "What to get details for. One of:\n"
                "- 'webhook_event': full webhook event including raw payload, device info, and matched workflows.\n"
                "    Required: id. Forbidden: section.\n"
                "- 'report': post-deployment validation report. Returns summary counts (pass/warn/fail per device type).\n"
                "    Required: id. Optional: section to fetch full data for one section.\n"
                "- 'dashboard': compact system overview with 7-day stats (workflows, executions, backups, webhooks, reports).\n"
                "    Required: none. Forbidden: id, section."
            ),
        ),
    ],
    id: Annotated[
        str,
        Field(
            description=(
                "MongoDB ObjectId string (24 hex chars), obtained from the 'id' field of a search() result. "
                "Required when type is 'webhook_event' or 'report'. Forbidden when type='dashboard'. "
                "Example: '507f1f77bcf86cd799439011'."
            )
        ),
    ] = "",
    section: Annotated[
        str,
        Field(
            description=(
                "ONLY valid when type='report'. Returns full data for one section instead of the summary. "
                "One of: 'aps', 'switches', 'gateways', 'template_variables'."
            )
        ),
    ] = "",
) -> str:
    """Get full details for a single webhook event, validation report, or the system dashboard overview.

    This tool is read-only. Typical workflow:
    - First call search() to find an item and get its id.
    - Then call get_details(type=..., id=...) to see its full payload.
    - For Mist configuration object versions, use backup(action='object_info'/'version_detail') instead.
    """
    validated = _validate_details_inputs(detail_type=type, id_value=id, section=section)

    dispatchers: dict[str, Any] = {
        "webhook_event": _webhook_event,
        "report": _report,
        "dashboard": _dashboard,
    }

    handler = dispatchers[validated["type"]]

    return await handler(id=validated["id"], section=validated["section"])


async def _webhook_event(*, id: str, **_kwargs) -> str:
    """Get a webhook event with full payload."""
    from beanie import PydanticObjectId

    from app.modules.automation.models.webhook import WebhookEvent

    try:
        event = await WebhookEvent.get(PydanticObjectId(id))
    except Exception as exc:
        raise ToolError(
            f"Invalid webhook event id '{id}': not a valid 24-char hex MongoDB ObjectId."
        ) from exc

    if not event:
        raise ToolError(f"Webhook event '{id}' not found")

    # Truncate payload if excessively large
    payload = event.payload
    if payload:
        payload_str = str(payload)
        if len(payload_str) > 3000:
            payload = truncate_value(payload_str, 3000)

    return to_json(
        {
            "id": str(event.id),
            "webhook_type": event.webhook_type,
            "webhook_topic": event.webhook_topic,
            "event_type": event.event_type,
            "device_name": event.device_name,
            "device_mac": event.device_mac,
            "site_name": event.site_name,
            "site_id": event.site_id,
            "payload": payload,
            "processed": event.processed,
            "matched_workflows": event.matched_workflows,
            "executions_triggered": event.executions_triggered,
            "received_at": event.received_at,
        }
    )


async def _report(*, id: str, section: str, **_kwargs) -> str:
    """Get a validation report's results."""
    from beanie import PydanticObjectId

    from app.modules.reports.models import ReportJob

    try:
        job = await ReportJob.get(PydanticObjectId(id))
    except Exception as exc:
        raise ToolError(
            f"Invalid report id '{id}': not a valid 24-char hex MongoDB ObjectId."
        ) from exc

    if not job:
        raise ToolError(f"Report '{id}' not found")

    result = job.result or {}

    if section:
        # Return full section data capped at 50 items
        section_data = result.get(section)
        if section_data is None:
            raise ToolError(f"Section '{section}' not found. Available: {', '.join(result.keys())}")
        if isinstance(section_data, list):
            section_data = cap_list(section_data, 50)
        return to_json({"id": str(job.id), "site_name": job.site_name, "section": section, "data": section_data})

    # Build summary counts per section
    summary: dict = {}
    for key in ("aps", "switches", "gateways"):
        items = result.get(key, [])
        if isinstance(items, list):
            total = len(items)
            pass_count = sum(1 for i in items if _item_status(i) == "pass")
            warn_count = sum(1 for i in items if _item_status(i) == "warn")
            fail_count = sum(1 for i in items if _item_status(i) == "fail")
            summary[key] = {"total": total, "pass": pass_count, "warn": warn_count, "fail": fail_count}

    tv = result.get("template_variables")
    if tv:
        summary["template_variables"] = {"total": len(tv) if isinstance(tv, list) else 0}

    return to_json(
        {
            "id": str(job.id),
            "report_type": job.report_type.value if hasattr(job.report_type, "value") else str(job.report_type),
            "site_name": job.site_name,
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "summary": summary,
        }
    )


def _item_status(item: dict) -> str:
    """Extract status from a report item (AP/switch/gateway)."""
    return (item.get("status") or item.get("overall_status") or "unknown").lower()


async def _dashboard(**_kwargs) -> str:
    """Get compact dashboard overview stats for the last 7 days."""
    import asyncio

    from app.modules.automation.models.execution import WorkflowExecution
    from app.modules.automation.models.webhook import WebhookEvent
    from app.modules.automation.models.workflow import Workflow
    from app.modules.backup.models import BackupJob
    from app.modules.reports.models import ReportJob

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    def _cnt(row: dict, key: str) -> int:
        bucket = row.get(key, [])
        return bucket[0]["n"] if bucket else 0

    # Run all 5 aggregation queries in parallel
    wf_fut, ex_fut, bk_fut, wh_fut, rp_fut = await asyncio.gather(
        Workflow.aggregate(
            [
                {
                    "$facet": {
                        "total": [{"$count": "n"}],
                        "enabled": [{"$match": {"status": "enabled"}}, {"$count": "n"}],
                    }
                }
            ]
        ).to_list(),
        WorkflowExecution.aggregate(
            [
                {"$match": {"started_at": {"$gte": cutoff}, "is_simulation": False}},
                {
                    "$facet": {
                        "total": [{"$count": "n"}],
                        "succeeded": [{"$match": {"status": "success"}}, {"$count": "n"}],
                        "failed": [{"$match": {"status": {"$in": ["failed", "timeout"]}}}, {"$count": "n"}],
                    }
                },
            ]
        ).to_list(),
        BackupJob.aggregate(
            [
                {"$match": {"created_at": {"$gte": cutoff}}},
                {
                    "$facet": {
                        "total": [{"$count": "n"}],
                        "completed": [{"$match": {"status": "completed"}}, {"$count": "n"}],
                        "failed": [{"$match": {"status": "failed"}}, {"$count": "n"}],
                    }
                },
            ]
        ).to_list(),
        WebhookEvent.aggregate(
            [
                {"$match": {"received_at": {"$gte": cutoff}}},
                {
                    "$facet": {
                        "total": [{"$count": "n"}],
                        "processed": [{"$match": {"processed": True}}, {"$count": "n"}],
                    }
                },
            ]
        ).to_list(),
        ReportJob.aggregate(
            [
                {"$match": {"created_at": {"$gte": cutoff}}},
                {
                    "$facet": {
                        "total": [{"$count": "n"}],
                        "completed": [{"$match": {"status": "completed"}}, {"$count": "n"}],
                        "failed": [{"$match": {"status": "failed"}}, {"$count": "n"}],
                    }
                },
            ]
        ).to_list(),
    )

    wf_row = wf_fut[0] if wf_fut else {}
    ex_row = ex_fut[0] if ex_fut else {}
    bk_row = bk_fut[0] if bk_fut else {}
    wh_row = wh_fut[0] if wh_fut else {}
    rp_row = rp_fut[0] if rp_fut else {}

    return to_json(
        {
            "workflows": {"total": _cnt(wf_row, "total"), "enabled": _cnt(wf_row, "enabled")},
            "executions_7d": {
                "total": _cnt(ex_row, "total"),
                "succeeded": _cnt(ex_row, "succeeded"),
                "failed": _cnt(ex_row, "failed"),
            },
            "backups_7d": {
                "total": _cnt(bk_row, "total"),
                "completed": _cnt(bk_row, "completed"),
                "failed": _cnt(bk_row, "failed"),
            },
            "webhooks_7d": {"total": _cnt(wh_row, "total"), "processed": _cnt(wh_row, "processed")},
            "reports_7d": {
                "total": _cnt(rp_row, "total"),
                "completed": _cnt(rp_row, "completed"),
                "failed": _cnt(rp_row, "failed"),
            },
        }
    )

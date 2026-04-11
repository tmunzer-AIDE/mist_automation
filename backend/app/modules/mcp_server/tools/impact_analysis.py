"""
MCP tools for querying impact analysis monitoring sessions.
"""

import re
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from app.modules.mcp_server.helpers import cap_list, to_json
from app.modules.mcp_server.server import mcp
from app.modules.mcp_server.tools.utils import is_placeholder, is_uuid

_SESSION_STATUS_VALUES: set[str] = {
    "pending",
    "baseline_capture",
    "awaiting_config",
    "monitoring",
    "validating",
    "completed",
    "failed",
    "cancelled",
}
_DEVICE_TYPES: set[str] = {"ap", "switch", "gateway"}
_MAC_PATTERN = re.compile(r"^[0-9a-f]{2}([-:])[0-9a-f]{2}(?:\1[0-9a-f]{2}){4}$", re.IGNORECASE)


def _validate_session_search_inputs(
    *,
    status: str,
    site_id: str,
    device_type: str,
    device_mac: str,
) -> dict[str, str]:
    normalized_status = status.strip().lower()
    if normalized_status and normalized_status not in _SESSION_STATUS_VALUES:
        raise ToolError(
            f"Invalid status '{status}'. Use: {', '.join(sorted(_SESSION_STATUS_VALUES))}"
        )

    normalized_site_id = site_id.strip()
    if normalized_site_id:
        if is_placeholder(normalized_site_id):
            raise ToolError(
                f"Invalid site_id '{site_id}': unresolved placeholders are not allowed"
            )
        if not is_uuid(normalized_site_id):
            raise ToolError(f"Invalid site_id '{site_id}'. site_id must be a real UUID")

    normalized_device_type = device_type.strip().lower()
    if normalized_device_type and normalized_device_type not in _DEVICE_TYPES:
        raise ToolError(
            f"Invalid device_type '{device_type}'. Use: {', '.join(sorted(_DEVICE_TYPES))}"
        )

    normalized_mac = device_mac.strip().lower()
    if normalized_mac:
        if is_placeholder(normalized_mac):
            raise ToolError(
                f"Invalid device_mac '{device_mac}': unresolved placeholders are not allowed"
            )
        if not _MAC_PATTERN.match(normalized_mac):
            raise ToolError(
                f"Invalid device_mac '{device_mac}'. Use format aa:bb:cc:dd:ee:ff"
            )

    return {
        "status": normalized_status,
        "site_id": normalized_site_id,
        "device_type": normalized_device_type,
        "device_mac": normalized_mac,
    }


@mcp.tool()
async def search_impact_sessions(
    status: Annotated[
        str,
        Field(
            description=(
                "Filter by session status. "
                "One of: 'pending', 'baseline_capture', 'awaiting_config', 'monitoring', "
                "'validating', 'completed', 'failed', 'cancelled'. Empty string for all."
            ),
        ),
    ] = "",
    site_id: Annotated[
        str,
        Field(description="Filter by Mist site UUID."),
    ] = "",
    device_type: Annotated[
        str,
        Field(description="Filter by device type: 'ap', 'switch', or 'gateway'."),
    ] = "",
    device_mac: Annotated[
        str,
        Field(description="Filter by device MAC address."),
    ] = "",
    limit: Annotated[
        int,
        Field(description="Max results to return (1-25).", ge=1, le=25),
    ] = 10,
) -> str:
    """Search impact analysis monitoring sessions with optional filters.

    Returns a compact list of sessions with id, site, device, status, and incident/change counts.
    Use get_impact_session_detail for full details on a specific session.
    """
    from app.modules.impact_analysis.models import MonitoringSession

    validated = _validate_session_search_inputs(
        status=status,
        site_id=site_id,
        device_type=device_type,
        device_mac=device_mac,
    )

    query: dict[str, Any] = {}
    if validated["status"]:
        query["status"] = validated["status"]
    if validated["site_id"]:
        query["site_id"] = validated["site_id"]
    if validated["device_type"]:
        query["device_type"] = validated["device_type"]
    if validated["device_mac"]:
        query["device_mac"] = validated["device_mac"]

    total = await MonitoringSession.find(query).count()
    sessions = await MonitoringSession.find(query).sort("-created_at").limit(limit).to_list()

    return to_json(
        {
            "results": [_session_summary(s) for s in sessions],
            "total": total,
        }
    )


@mcp.tool()
async def get_impact_session_detail(
    id: Annotated[
        str,
        Field(
            description="MongoDB document ID of the monitoring session. Get this from search_impact_sessions results."
        ),
    ],
) -> str:
    """Get full details of an impact analysis monitoring session, including config changes, incidents, SLE delta, validation results, and AI assessment."""
    from beanie import PydanticObjectId

    from app.modules.impact_analysis.models import MonitoringSession

    session_id = id.strip()
    if not session_id:
        raise ToolError("id is required")
    if is_placeholder(session_id):
        raise ToolError(f"Invalid id '{id}': unresolved placeholders are not allowed")

    try:
        session = await MonitoringSession.get(PydanticObjectId(session_id))
    except Exception:
        raise ToolError(f"Invalid session id '{id}'")

    if not session:
        raise ToolError(f"Monitoring session '{id}' not found")

    result = _session_summary(session)

    # Add full detail fields
    result["config_changes"] = cap_list(
        [
            {
                "event_type": c.event_type,
                "device_name": c.device_name,
                "timestamp": c.timestamp.isoformat() if c.timestamp else None,
            }
            for c in session.config_changes
        ],
        50,
    )
    result["incidents"] = cap_list(
        [
            {
                "event_type": i.event_type,
                "device_name": i.device_name,
                "severity": i.severity,
                "is_revert": i.is_revert,
                "resolved": i.resolved,
                "timestamp": i.timestamp.isoformat() if i.timestamp else None,
            }
            for i in session.incidents
        ],
        50,
    )
    result["sle_delta"] = session.sle_delta
    result["validation_results"] = session.validation_results
    result["ai_assessment"] = session.ai_assessment

    return to_json(result)


def _session_summary(session: Any) -> dict[str, Any]:
    """Convert a MonitoringSession to a compact summary dict."""
    return {
        "id": str(session.id),
        "site_id": session.site_id,
        "site_name": session.site_name,
        "device_mac": session.device_mac,
        "device_name": session.device_name,
        "device_type": session.device_type.value if hasattr(session.device_type, "value") else str(session.device_type),
        "status": session.status.value if hasattr(session.status, "value") else str(session.status),
        "config_change_count": len(session.config_changes),
        "incident_count": len(session.incidents),
        "has_impact": getattr(session, "impact_severity", "none") != "none",
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }

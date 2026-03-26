"""
MCP tools for querying impact analysis monitoring sessions.
"""

from typing import Annotated, Any

from pydantic import Field

from app.modules.mcp_server.helpers import cap_list, to_json
from app.modules.mcp_server.server import mcp


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

    limit = min(limit, 25)

    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if site_id:
        query["site_id"] = site_id
    if device_type:
        query["device_type"] = device_type
    if device_mac:
        query["device_mac"] = device_mac

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

    if not id:
        return to_json({"error": "id is required"})

    try:
        session = await MonitoringSession.get(PydanticObjectId(id))
    except Exception:
        return to_json({"error": f"Invalid session id '{id}'"})

    if not session:
        return to_json({"error": f"Monitoring session '{id}' not found"})

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

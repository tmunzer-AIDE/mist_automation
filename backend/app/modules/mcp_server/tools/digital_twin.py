"""
MCP tool: digital_twin — pre-deployment simulation for Mist config changes.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from app.modules.mcp_server.helpers import _elicit, to_json
from app.modules.mcp_server.server import mcp, mcp_user_id_var


@mcp.tool()
async def digital_twin(
    ctx: Context,
    action: Annotated[
        str,
        Field(
            description=(
                "Action to perform. "
                "'simulate': validate proposed writes, returns check results. "
                "'approve': deploy staged writes (requires user confirmation). "
                "'reject': cancel the session. "
                "'status': check current session state. "
                "'history': list recent sessions."
            ),
        ),
    ],
    writes: Annotated[
        str,
        Field(
            description=(
                "JSON array of proposed writes for 'simulate' action. "
                'Each write: {"method": "POST|PUT|DELETE", "endpoint": "/api/v1/...", "body": {...}}. '
                'Example: [{"method": "PUT", "endpoint": "/api/v1/sites/abc/setting", "body": {"vars": {"vlan": "100"}}}]'
            ),
        ),
    ] = "[]",
    session_id: Annotated[
        str,
        Field(description="Twin session ID for approve/reject/status actions."),
    ] = "",
) -> str:
    """Pre-deployment simulation engine (Digital Twin).

    Validates proposed Mist configuration changes against the current network
    state before execution. Detects IP conflicts, VLAN collisions, template
    variable issues, SSID duplicates, DHCP misconfigurations, and more.

    Workflow:
    1. Call with action='simulate' and your proposed writes
    2. Review the check results — fix any issues
    3. Re-simulate with corrected writes if needed
    4. Call action='approve' to deploy (user confirmation required)
    """
    import json as json_mod

    from app.config import settings
    from app.modules.digital_twin.services import twin_service

    user_id = mcp_user_id_var.get()
    if not user_id:
        return to_json({"error": "User context not available"})

    org_id = settings.mist_org_id or ""

    if action == "simulate":
        try:
            write_list = json_mod.loads(writes) if isinstance(writes, str) else writes
        except json_mod.JSONDecodeError:
            return to_json({"error": "Invalid JSON in writes parameter"})

        if not write_list:
            return to_json({"error": "No writes provided. Provide a JSON array of {method, endpoint, body} objects."})

        existing_id = session_id if session_id else None

        session = await twin_service.simulate(
            user_id=user_id,
            org_id=org_id,
            writes=write_list,
            source="llm_chat",
            existing_session_id=existing_id,
        )

        report = session.prediction_report
        result: dict[str, Any] = {
            "session_id": str(session.id),
            "status": session.status.value,
            "overall_severity": session.overall_severity,
            "remediation_count": session.remediation_count,
        }

        if report:
            result["summary"] = report.summary
            result["execution_safe"] = report.execution_safe
            result["counts"] = {
                "total": report.total_checks,
                "passed": report.passed,
                "warnings": report.warnings,
                "errors": report.errors,
                "critical": report.critical,
            }
            result["issues"] = [
                {
                    "check": r.check_id,
                    "name": r.check_name,
                    "status": r.status,
                    "summary": r.summary,
                    "details": r.details,
                    "remediation_hint": r.remediation_hint,
                }
                for r in report.check_results
                if r.status not in ("pass", "skipped")
            ]

        return to_json(result)

    elif action == "approve":
        if not session_id:
            return to_json({"error": "session_id required for approve action"})

        session = await twin_service.get_session(session_id)
        if not session:
            return to_json({"error": f"Session {session_id} not found"})

        write_count = len(session.staged_writes)
        report = session.prediction_report
        summary_parts = [f"{write_count} write(s) to deploy"]
        if report and report.warnings:
            summary_parts.append(f"{report.warnings} warning(s) acknowledged")
        if session.remediation_count:
            summary_parts.append(f"{session.remediation_count} fix iteration(s) applied")

        description = f"Digital Twin deployment: {', '.join(summary_parts)}"

        approval_data = {
            "session_id": str(session.id),
            "writes_count": write_count,
            "overall_severity": session.overall_severity,
            "summary": report.summary if report else "No validation report",
            "execution_safe": report.execution_safe if report else True,
            "affected_sites": session.affected_sites,
            "remediation_count": session.remediation_count,
        }

        await _elicit(
            {
                "type": "elicitation",
                "description": description,
                "elicitation_type": "twin_approve",
                "data": approval_data,
            },
            description,
            120.0,
        )

        session = await twin_service.approve_and_execute(session_id)
        return to_json(
            {
                "session_id": str(session.id),
                "status": session.status.value,
                "message": "Deployment complete" if session.status.value == "deployed" else "Deployment failed",
            }
        )

    elif action == "reject":
        if not session_id:
            return to_json({"error": "session_id required for reject action"})
        session = await twin_service.reject_session(session_id)
        return to_json({"session_id": str(session.id), "status": session.status.value})

    elif action == "status":
        if not session_id:
            return to_json({"error": "session_id required for status action"})
        session = await twin_service.get_session(session_id)
        if not session:
            return to_json({"error": f"Session {session_id} not found"})
        return to_json(
            {
                "session_id": str(session.id),
                "status": session.status.value,
                "severity": session.overall_severity,
                "writes": len(session.staged_writes),
                "remediation_count": session.remediation_count,
            }
        )

    elif action == "history":
        sessions = await twin_service.list_sessions(user_id, limit=10)
        return to_json(
            {
                "sessions": [
                    {
                        "id": str(s.id),
                        "status": s.status.value,
                        "severity": s.overall_severity,
                        "source": s.source,
                        "writes": len(s.staged_writes),
                        "created_at": s.created_at,
                    }
                    for s in sessions
                ]
            }
        )

    return to_json({"error": f"Unknown action: {action}. Use simulate, approve, reject, status, or history."})

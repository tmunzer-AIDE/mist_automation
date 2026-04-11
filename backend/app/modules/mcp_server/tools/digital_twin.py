"""
MCP tool: digital_twin — pre-deployment simulation for Mist config changes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from mcp.server.fastmcp import Context
from pydantic import Field

from app.modules.mcp_server.helpers import _elicit, to_json
from app.modules.mcp_server.server import mcp, mcp_user_id_var
from app.modules.mcp_server.tools.utils import endpoint_has_placeholder, is_placeholder

_TWIN_ACTIONS: set[str] = {"simulate", "approve", "reject", "status", "history"}
_WRITE_METHODS: set[str] = {"POST", "PUT", "DELETE"}


def _validate_twin_inputs(
    *,
    action: str,
    writes: list[dict[str, Any]] | None,
    session_id: str,
) -> dict[str, Any]:
    normalized_action = action.strip().lower()
    if normalized_action not in _TWIN_ACTIONS:
        raise ToolError(
            f"Unknown action '{action}'. Use simulate, approve, reject, status, or history"
        )

    normalized_session_id = session_id.strip()
    if normalized_session_id and is_placeholder(normalized_session_id):
        raise ToolError(f"Invalid session_id '{session_id}': unresolved placeholders are not allowed")

    normalized_writes: list[dict[str, Any]] = []
    if writes is not None:
        if not isinstance(writes, list):
            raise ToolError("writes must be a JSON array of {method, endpoint, body} objects")
        for idx, write in enumerate(writes):
            if not isinstance(write, dict):
                raise ToolError(f"writes[{idx}] must be an object")

            method = str(write.get("method", "")).strip().upper()
            endpoint = str(write.get("endpoint", "")).strip()
            body = write.get("body")

            if method not in _WRITE_METHODS:
                raise ToolError(f"writes[{idx}].method must be one of: POST, PUT, DELETE")
            if not endpoint:
                raise ToolError(f"writes[{idx}].endpoint is required")
            if endpoint_has_placeholder(endpoint):
                raise ToolError(
                    f"writes[{idx}].endpoint contains unresolved placeholders: {endpoint}"
                )
            if method in {"POST", "PUT"} and (body is None or not isinstance(body, dict)):
                raise ToolError(f"writes[{idx}].body must be an object for method={method}")
            if method == "DELETE" and body is not None and not isinstance(body, dict):
                raise ToolError("writes body must be an object when provided")

            normalized_write: dict[str, Any] = {"method": method, "endpoint": endpoint}
            if body is not None:
                normalized_write["body"] = body
            normalized_writes.append(normalized_write)

    if normalized_action == "simulate":
        if not normalized_writes:
            raise ToolError("No writes provided. Provide a JSON array of {method, endpoint, body} objects")
    elif normalized_action in {"approve", "reject", "status"}:
        if not normalized_session_id:
            raise ToolError(f"session_id required for {normalized_action} action")
        if normalized_writes:
            raise ToolError(f"writes is not supported for action='{normalized_action}'")
    elif normalized_action == "history":
        if normalized_session_id:
            raise ToolError("session_id is not supported for action='history'")
        if normalized_writes:
            raise ToolError("writes is not supported for action='history'")

    return {
        "action": normalized_action,
        "writes": normalized_writes,
        "session_id": normalized_session_id,
    }


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
        list[dict[str, Any]] | None,
        Field(
            description=(
                "Array of proposed writes for 'simulate' action. "
                'Each write: {"method": "POST|PUT|DELETE", "endpoint": "/api/v1/...", "body": {...}}.\n'
                "\n"
                "MANDATORY PRECONDITION:\n"
                "- You MUST resolve org/site/object names to real UUIDs before calling this tool.\n"
                "- Endpoints containing placeholders are invalid and will be rejected, including: {site_id}, {device_id}, <site_id>, :site_id.\n"
                "- PUT/DELETE writes must reference existing object IDs from current data/backups.\n"
                "\n"
                "ENDPOINT FORMAT RULES:\n"
                "- Site-level: /api/v1/sites/{site_id}/{resource} (POST) or /api/v1/sites/{site_id}/{resource}/{object_id} (PUT/DELETE)\n"
                "- Org-level: /api/v1/orgs/{org_id}/{resource} (POST) or /api/v1/orgs/{org_id}/{resource}/{object_id} (PUT/DELETE)\n"
                "- Singletons (no object_id): /api/v1/sites/{site_id}/setting, /api/v1/orgs/{org_id}/setting\n"
                "- Use real UUIDs for site_id, org_id, and object_id; never send names or unresolved variables.\n"
                "\n"
                "VALID SITE RESOURCES: wlans, networks, devices, maps, zones, rssizones, psks, assets, "
                "beacons, vbeacons, wxrules, wxtags, webhooks, evpn_topologies. Singletons: setting, info.\n"
                "\n"
                "VALID ORG RESOURCES: wlans, networks, networktemplates, rftemplates, deviceprofiles, "
                "gatewaytemplates, aptemplates, sitetemplates, templates, vpns, psks, pskportals, nacrules, "
                "nactags, nacportals, services, servicepolicies, secpolicies, wxrules, alarmtemplates, webhooks, "
                "sites, sitegroups, mxtunnels, mxclusters, mxedges, avprofiles, idpprofiles, secintelprofiles, "
                "ssos, ssoroles, usermacs, assets, assetfilters, evpn_topologies, inventory. Singleton: setting.\n"
                "\n"
                "EXAMPLES:\n"
                '- Create WLAN: {"method": "POST", "endpoint": "/api/v1/sites/0fdb73c9-2c77-4b45-8f5b-4b30f5d6df7c/wlans", "body": {"ssid": "Guest", "auth": {"type": "open"}}}\n'
                '- Update network: {"method": "PUT", "endpoint": "/api/v1/orgs/2818e386-8dec-2562-9ede-5b8a0fbbdc71/networks/6f4bf402-45f9-2a56-6c8b-7f83d3bc98e4", "body": {"vlan_id": 100, "subnet": "10.1.0.0/24"}}\n'
                '- Update site setting: {"method": "PUT", "endpoint": "/api/v1/sites/0fdb73c9-2c77-4b45-8f5b-4b30f5d6df7c/setting", "body": {"vars": {"vlan_guest": "200"}}}\n'
                '- Change switch port profile: {"method": "PUT", "endpoint": "/api/v1/sites/0fdb73c9-2c77-4b45-8f5b-4b30f5d6df7c/devices/eb4f89f6-f6de-4f13-a3ef-9f0c61f5a31f", '
                '"body": {"port_config": {"ge-0/0/9": {"usage": "disabled", "port_network": "disabled"}}}}\n'
                '- Delete WLAN: {"method": "DELETE", "endpoint": "/api/v1/sites/0fdb73c9-2c77-4b45-8f5b-4b30f5d6df7c/wlans/3f4f71c8-90f4-4b9c-a2b0-5485780f5b62"}'
            ),
        ),
    ] = None,
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
    1. Resolve org/site/object names to real UUIDs.
    2. Call with action='simulate' and your proposed writes.
    3. Review the check results — fix any issues.
    4. Re-simulate with corrected writes if needed.
    5. Call action='approve' to deploy (user confirmation required).
    """
    _ = ctx

    from app.config import settings
    from app.modules.digital_twin.services import twin_service

    validated = _validate_twin_inputs(action=action, writes=writes, session_id=session_id)

    user_id = mcp_user_id_var.get()
    if not user_id:
        raise ToolError("User context not available")

    org_id = settings.mist_org_id or ""
    action_value = validated["action"]
    session_id_value = validated["session_id"]

    if action_value == "simulate":
        write_list = validated["writes"]
        existing_id = session_id_value if session_id_value else None

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

    elif action_value == "approve":
        session = await twin_service.get_session(session_id_value)
        if not session:
            raise ToolError(f"Session {session_id_value} not found")
        if str(session.user_id) != user_id:
            raise ToolError("Session not found")

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

        try:
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
        except ValueError as exc:
            raise ToolError("Deployment cancelled by user") from exc

        session = await twin_service.approve_and_execute(session_id_value, user_id=user_id)
        return to_json(
            {
                "session_id": str(session.id),
                "status": session.status.value,
                "message": "Deployment complete" if session.status.value == "deployed" else "Deployment failed",
            }
        )

    elif action_value == "reject":
        session = await twin_service.reject_session(session_id_value, user_id=user_id)
        return to_json({"session_id": str(session.id), "status": session.status.value})

    elif action_value == "status":
        session = await twin_service.get_session(session_id_value)
        if not session:
            raise ToolError(f"Session {session_id_value} not found")
        if str(session.user_id) != user_id:
            raise ToolError("Session not found")
        return to_json(
            {
                "session_id": str(session.id),
                "status": session.status.value,
                "severity": session.overall_severity,
                "writes": len(session.staged_writes),
                "remediation_count": session.remediation_count,
            }
        )

    elif action_value == "history":
        sessions, _total = await twin_service.list_sessions(user_id, limit=10)
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

    raise ToolError(f"Unsupported action '{action_value}'")

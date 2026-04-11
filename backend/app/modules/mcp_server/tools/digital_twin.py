"""
MCP tool: digital_twin — pre-deployment simulation for Mist config changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field

from app.modules.mcp_server.helpers import _elicit, to_json
from app.modules.mcp_server.server import mcp, mcp_user_id_var
from app.modules.mcp_server.tools.utils import endpoint_has_placeholder, is_placeholder, is_uuid


class TwinActionType(str, Enum):
    SIMULATE = 'simulate'
    APPROVE = 'approve'
    REJECT = 'reject'
    STATUS = 'status'
    HISTORY = 'history'


class TwinWriteMethod(str, Enum):
    POST = 'POST'
    PUT = 'PUT'
    DELETE = 'DELETE'


class TwinWriteInput(BaseModel):
    method: TwinWriteMethod
    endpoint: str
    body: dict[str, Any] | None = None


_TWIN_ACTIONS: set[str] = {action.value for action in TwinActionType}
_WRITE_METHODS: set[str] = {'POST', 'PUT', 'DELETE'}


def _resolve_twin_org_id(
    explicit_org_id: str | None,
    config_org_id: str | None,
    env_org_id: str | None,
) -> str:
    """Resolve Mist org ID for Digital Twin operations.

    Preference order: explicit tool input, SystemConfig value, env fallback.
    """
    explicit = (explicit_org_id or '').strip()
    if explicit:
        if is_placeholder(explicit):
            raise ToolError('org_id must be a real UUID, not a placeholder')
        if not is_uuid(explicit):
            raise ToolError(f"org_id '{explicit}' must be a valid UUID")
        return explicit

    resolved = (config_org_id or '').strip() or (env_org_id or '').strip()
    if not resolved:
        raise ToolError('Mist Organization ID not configured. Set it in Admin Settings before simulation')
    if not is_uuid(resolved):
        raise ToolError('Configured Mist Organization ID is invalid. Set a valid UUID in Admin Settings')
    return resolved


def _validate_twin_inputs(
    *,
    action: TwinActionType | str,
    writes: Sequence[TwinWriteInput | dict[str, Any]] | None,
    session_id: str,
    resolved_org_id: str | None = None,
) -> dict[str, Any]:
    """Validate action-specific input coherence for the Digital Twin tool."""
    from app.modules.digital_twin.services.endpoint_parser import parse_endpoint

    normalized_action = action.value if isinstance(action, TwinActionType) else str(action).strip().lower()
    if normalized_action not in _TWIN_ACTIONS:
        raise ToolError(f"Unknown action '{action}'. Use simulate, approve, reject, status, or history")

    normalized_session_id = session_id.strip()
    if normalized_session_id and is_placeholder(normalized_session_id):
        raise ToolError(f"Invalid session_id '{session_id}': unresolved placeholders are not allowed")

    normalized_writes: list[dict[str, Any]] = []

    if normalized_action in {'approve', 'reject', 'status'}:
        if not normalized_session_id:
            raise ToolError(f'session_id required for {normalized_action} action')
        if writes:
            raise ToolError(f"writes is not supported for action='{normalized_action}'")
    elif normalized_action == 'history':
        if normalized_session_id:
            raise ToolError("session_id is not supported for action='history'")
        if writes:
            raise ToolError("writes is not supported for action='history'")
    else:
        if writes is None:
            raise ToolError('No writes provided. Provide a JSON array of {method, endpoint, body} objects')
        if not isinstance(writes, list):
            raise ToolError('writes must be a JSON array of {method, endpoint, body} objects')

        for idx, write in enumerate(writes):
            if isinstance(write, TwinWriteInput):
                write_data = write.model_dump(mode='python')
            elif isinstance(write, dict):
                write_data = write
            else:
                raise ToolError(f'writes[{idx}] must be an object')

            method_raw = write_data.get('method', '')
            if isinstance(method_raw, TwinWriteMethod):
                method = method_raw.value
            else:
                method = str(method_raw).strip().upper()

            endpoint = str(write_data.get('endpoint', '')).strip()
            body = write_data.get('body')

            if method not in _WRITE_METHODS:
                raise ToolError(f'writes[{idx}].method must be one of: POST, PUT, DELETE')
            if not endpoint:
                raise ToolError(f'writes[{idx}].endpoint is required')
            if endpoint_has_placeholder(endpoint):
                raise ToolError(f'writes[{idx}].endpoint contains unresolved placeholders: {endpoint}')
            if method in {'POST', 'PUT'} and (body is None or not isinstance(body, dict)):
                raise ToolError(f'writes[{idx}].body must be an object for method={method}')
            if method == 'DELETE' and body is not None and not isinstance(body, dict):
                raise ToolError('writes body must be an object when provided')

            parsed = parse_endpoint(method, endpoint)
            if parsed.error:
                raise ToolError(f'writes[{idx}].endpoint is invalid: {parsed.error}')
            if parsed.site_id and not is_uuid(parsed.site_id):
                raise ToolError(f"writes[{idx}].endpoint site_id must be a UUID, got '{parsed.site_id}'")
            if parsed.org_id and not is_uuid(parsed.org_id):
                raise ToolError(f"writes[{idx}].endpoint org_id must be a UUID, got '{parsed.org_id}'")
            if parsed.org_id and resolved_org_id and parsed.org_id != resolved_org_id:
                raise ToolError(f"writes[{idx}].endpoint org_id '{parsed.org_id}' does not match resolved org_id '{resolved_org_id}'")

            normalized_write: dict[str, Any] = {'method': method, 'endpoint': endpoint}
            if body is not None:
                normalized_write['body'] = body
            normalized_writes.append(normalized_write)

        if not normalized_writes:
            raise ToolError('No writes provided. Provide a JSON array of {method, endpoint, body} objects')

    return {
        'action': normalized_action,
        'writes': normalized_writes,
        'session_id': normalized_session_id,
    }


@mcp.tool()
async def digital_twin(
    ctx: Context,
    action: Annotated[
        TwinActionType,
        Field(
            description=(
                'Action to perform: simulate | approve | reject | status | history. '
                "Use 'simulate' first, then 'approve' only when execution_safe is true."
            )
        ),
    ],
    writes: Annotated[
        list[TwinWriteInput] | None,
        Field(
            description=(
                "Writes for simulate action only. "
                'Each write: {"method": "POST|PUT|DELETE", "endpoint": "/api/v1/...", "body": {...}}. '
                'Endpoints are strict-validated before simulation.'
            )
        ),
    ] = None,
    org_id: Annotated[
        str,
        Field(
            description=(
                'Optional Mist org UUID override for this call. '
                'If omitted, uses SystemConfig mist_org_id or env fallback.'
            )
        ),
    ] = '',
    session_id: Annotated[
        str,
        Field(description='Twin session ID for approve/reject/status actions.'),
    ] = '',
) -> str:
    """Pre-deployment simulation engine (Digital Twin)."""
    _ = ctx

    from app.config import settings
    from app.models.system import SystemConfig
    from app.modules.digital_twin.services import twin_service

    user_id = mcp_user_id_var.get()
    if not user_id:
        raise ToolError('User context not available')

    config = await SystemConfig.get_config()
    config_org_id = config.mist_org_id if config else None
    resolved_org_id = _resolve_twin_org_id(org_id, config_org_id, settings.mist_org_id)
    validated = _validate_twin_inputs(
        action=action,
        writes=writes,
        session_id=session_id,
        resolved_org_id=resolved_org_id,
    )

    action_value = validated['action']
    session_id_value = validated['session_id']

    if action_value == 'simulate':
        write_list = validated['writes']
        existing_id = session_id_value if session_id_value else None

        session = await twin_service.simulate(
            user_id=user_id,
            org_id=resolved_org_id,
            writes=write_list,
            source='llm_chat',
            existing_session_id=existing_id,
        )

        report = session.prediction_report
        result: dict[str, Any] = {
            'session_id': str(session.id),
            'status': session.status.value,
            'overall_severity': session.overall_severity,
            'remediation_count': session.remediation_count,
        }

        if report:
            result['summary'] = report.summary
            result['execution_safe'] = report.execution_safe
            result['counts'] = {
                'total': report.total_checks,
                'passed': report.passed,
                'warnings': report.warnings,
                'errors': report.errors,
                'critical': report.critical,
            }
            result['issues'] = [
                {
                    'check': r.check_id,
                    'name': r.check_name,
                    'status': r.status,
                    'summary': r.summary,
                    'details': r.details,
                    'remediation_hint': r.remediation_hint,
                }
                for r in report.check_results
                if r.status not in ('pass', 'skipped')
            ]

        return to_json(result)

    if action_value == 'approve':
        session = await twin_service.get_session(session_id_value)
        if not session:
            raise ToolError(f'Session {session_id_value} not found')
        if str(session.user_id) != user_id:
            raise ToolError('Session not found')

        write_count = len(session.staged_writes)
        report = session.prediction_report
        summary_parts = [f'{write_count} write(s) to deploy']
        if report and report.warnings:
            summary_parts.append(f'{report.warnings} warning(s) acknowledged')
        if session.remediation_count:
            summary_parts.append(f'{session.remediation_count} fix iteration(s) applied')

        description = f"Digital Twin deployment: {', '.join(summary_parts)}"

        approval_data = {
            'session_id': str(session.id),
            'writes_count': write_count,
            'overall_severity': session.overall_severity,
            'summary': report.summary if report else 'No validation report',
            'execution_safe': report.execution_safe if report else True,
            'affected_sites': session.affected_sites,
            'remediation_count': session.remediation_count,
        }

        try:
            await _elicit(
                {
                    'type': 'elicitation',
                    'description': description,
                    'elicitation_type': 'twin_approve',
                    'data': approval_data,
                },
                description,
                120.0,
            )
        except ValueError as exc:
            raise ToolError('Deployment cancelled by user') from exc

        session = await twin_service.approve_and_execute(session_id_value, user_id=user_id)
        return to_json(
            {
                'session_id': str(session.id),
                'status': session.status.value,
                'message': 'Deployment complete' if session.status.value == 'deployed' else 'Deployment failed',
            }
        )

    if action_value == 'reject':
        session = await twin_service.reject_session(session_id_value, user_id=user_id)
        return to_json({'session_id': str(session.id), 'status': session.status.value})

    if action_value == 'status':
        session = await twin_service.get_session(session_id_value)
        if not session:
            raise ToolError(f'Session {session_id_value} not found')
        if str(session.user_id) != user_id:
            raise ToolError('Session not found')
        return to_json(
            {
                'session_id': str(session.id),
                'status': session.status.value,
                'severity': session.overall_severity,
                'writes': len(session.staged_writes),
                'remediation_count': session.remediation_count,
            }
        )

    sessions, _total = await twin_service.list_sessions(user_id, limit=10)
    return to_json(
        {
            'sessions': [
                {
                    'id': str(s.id),
                    'status': s.status.value,
                    'severity': s.overall_severity,
                    'source': s.source,
                    'writes': len(s.staged_writes),
                    'created_at': s.created_at,
                }
                for s in sessions
            ]
        }
    )

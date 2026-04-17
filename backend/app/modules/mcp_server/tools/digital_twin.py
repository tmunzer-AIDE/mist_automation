"""
MCP tool: digital_twin — pre-deployment simulation for Mist config changes.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastmcp.dependencies import CurrentContext
from fastmcp.exceptions import ToolError
from mcp.server.fastmcp import Context
from pydantic import Field

from app.modules.mcp_server.helpers import _elicit, to_json
from app.modules.mcp_server.server import mcp, mcp_user_id_var
from app.modules.mcp_server.tools.utils import is_placeholder, is_uuid

logger = structlog.get_logger(__name__)


class TwinActionType(str, Enum):
    SIMULATE = "simulate"
    APPROVE = "approve"
    REJECT = "reject"
    STATUS = "status"
    HISTORY = "history"


class Object_type(str, Enum):
    ORG_ALARMTEMPLATES = "org_alarmtemplates"
    ORG_WLANS = "org_wlans"
    ORG_SITEGROUPS = "org_sitegroups"
    ORG_AVPROFILES = "org_avprofiles"
    ORG_DEVICEPROFILES = "org_deviceprofiles"
    ORG_GATEWAYTEMPLATES = "org_gatewaytemplates"
    ORG_IDPPROFILES = "org_idpprofiles"
    ORG_AAMWPROFILES = "org_aamwprofiles"
    ORG_NACTAGS = "org_nactags"
    ORG_NACRULES = "org_nacrules"
    ORG_NETWORKTEMPLATES = "org_networktemplates"
    ORG_NETWORKS = "org_networks"
    ORG_PSKS = "org_psks"
    ORG_RFTEMPLATES = "org_rftemplates"
    ORG_SERVICES = "org_services"
    ORG_SERVICEPOLICIES = "org_servicepolicies"
    ORG_SITETEMPLATES = "org_sitetemplates"
    ORG_VPNS = "org_vpns"
    ORG_WEBHOOKS = "org_webhooks"
    ORG_WLANTEMPLATES = "org_wlantemplates"
    ORG_WXRULES = "org_wxrules"
    ORG_WXTAGS = "org_wxtags"
    SITE_DEVICES = "site_devices"
    SITE_EVPN_TOPOLOGIES = "site_evpn_topologies"
    SITE_INFO = "site_info"
    SITE_PSKS = "site_psks"
    SITE_SETTING = "site_setting"
    SITE_WEBHOOKS = "site_webhooks"
    SITE_WLANS = "site_wlans"
    SITE_WXRULES = "site_wxrules"
    SITE_WXTAGS = "site_wxtags"


class Action_type(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


_TWIN_ACTIONS: set[str] = {action.value for action in TwinActionType}
_TWIN_SESSION_ACTIONS: set[str] = {"approve", "reject", "status"}

# Caps the number of changes an LLM/external client can stage in a single
# simulate call. Each change triggers DB queries and snapshot builds, so an
# unbounded list is a DoS/resource-exhaustion surface.
_MAX_CHANGES_PER_SIMULATE = 50


def _twin_approve_messages() -> dict[Any, str]:
    """Sanitized messages for TwinApprovalError codes (mirrors REST _approve_error_response)."""
    from app.modules.digital_twin.services import twin_service

    return {
        twin_service.TwinApprovalErrorCode.NOT_FOUND: "Session not found",
        twin_service.TwinApprovalErrorCode.NOT_AWAITING_APPROVAL: "Session is not awaiting approval",
        twin_service.TwinApprovalErrorCode.NO_VALIDATION_REPORT: "Session has no validation report",
        twin_service.TwinApprovalErrorCode.BLOCKING_VALIDATION_ISSUES: "Session has blocking validation issues",
        twin_service.TwinApprovalErrorCode.PREFLIGHT_VALIDATION_ERRORS: "Session has preflight validation errors",
    }


_ACTION_TO_METHOD: dict[Action_type, str] = {
    Action_type.CREATE: "POST",
    Action_type.UPDATE: "PUT",
    Action_type.DELETE: "DELETE",
}

_MONGO_OBJECT_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")

_OBJECT_RESOURCE_OVERRIDES: dict[Object_type, str] = {
    # Mist uses /templates for WLAN template CRUD.
    Object_type.ORG_WLANTEMPLATES: "templates",
}

# Singleton object types map directly to an explicit URL template instead of the
# generic `{scope}/{id}/{resource}/{object_id}` builder. These endpoints have no
# object_id (the site_id IS the identifier) and only UPDATE is meaningful.
_SINGLETON_OAS_PATHS: dict[Object_type, str] = {
    Object_type.SITE_INFO: "/api/v1/sites/{site_id}",
    Object_type.SITE_SETTING: "/api/v1/sites/{site_id}/setting",
}

_ORG_OBJECT_TYPE_VALUES = ", ".join(sorted(obj.value for obj in Object_type if obj.value.startswith("org_")))
_SITE_OBJECT_TYPE_VALUES = ", ".join(sorted(obj.value for obj in Object_type if obj.value.startswith("site_")))


def _serialize_check_result(check: Any) -> dict[str, Any]:
    """Serialize one check result into an admin-focused diagnostics payload."""
    return {
        "check": check.check_id,
        "name": check.check_name,
        "layer": check.layer,
        "status": check.status,
        "summary": check.summary,
        "description": check.description,
        "pre_existing": bool(getattr(check, "pre_existing", False)),
        "affected_sites": list(getattr(check, "affected_sites", []) or []),
        "affected_objects": list(getattr(check, "affected_objects", []) or []),
        "details": list(getattr(check, "details", []) or []),
        "remediation_hint": check.remediation_hint,
    }


def _build_report_diagnostics(report: Any) -> dict[str, Any]:
    """Build consistent diagnostics blocks for simulation/status responses."""
    sorted_checks = sorted(report.check_results, key=lambda c: (c.layer, c.check_id))

    check_diagnostics = [_serialize_check_result(check) for check in sorted_checks]
    executed_checks = [
        {
            "check": item["check"],
            "name": item["name"],
            "layer": item["layer"],
            "status": item["status"],
            "summary": item["summary"],
        }
        for item in check_diagnostics
    ]
    issues = [item for item in check_diagnostics if item["status"] not in ("pass", "skipped")]
    decision_log = [
        f"L{item['layer']} {item['check']} [{item['status']}] {item['summary']}" for item in check_diagnostics
    ]

    return {
        "executed_checks": executed_checks,
        "issues": issues,
        "check_diagnostics": check_diagnostics,
        "decision_log": decision_log,
        "pre_existing_issue_count": sum(1 for item in issues if item["pre_existing"]),
        "introduced_issue_count": sum(1 for item in issues if not item["pre_existing"]),
    }


def _validate_session_id_format(session_id: str) -> None:
    """Validate Twin session identifiers are MongoDB ObjectId strings."""
    if not _MONGO_OBJECT_ID_RE.fullmatch(session_id):
        raise ToolError("session_id must be a valid Digital Twin session ID (24-character hex ObjectId)")


def _resolve_source_ref(client_name: str | None) -> str:
    """Normalize the MCP client name into a display label.

    Empty/None -> "Internal Chat" (in-app LLM chat has no external client).
    Trimmed client name -> displayed as-is.
    """
    if not client_name:
        return "Internal Chat"
    trimmed = client_name.strip()
    return trimmed or "Internal Chat"


def _first_payload_placeholder(value: Any, path: str = "payload") -> str | None:
    """Return the first payload path containing an unresolved placeholder value."""
    if isinstance(value, str):
        return path if is_placeholder(value) else None

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if is_placeholder(key_text):
                return f"{path}.{key_text}"
            found = _first_payload_placeholder(item, f"{path}.{key_text}")
            if found:
                return found
        return None

    if isinstance(value, list):
        for index, item in enumerate(value):
            found = _first_payload_placeholder(item, f"{path}[{index}]")
            if found:
                return found
        return None

    return None


def _normalize_optional_uuid(value: UUID | str | None, field_name: str) -> str | None:
    """Normalize optional UUID-like input to string and validate placeholders/format."""
    if value is None:
        return None

    normalized = str(value).strip()
    if not normalized:
        return None

    if is_placeholder(normalized):
        raise ToolError(f"{field_name} must be a real UUID, not a placeholder")
    if not is_uuid(normalized):
        raise ToolError(f"{field_name} '{normalized}' must be a valid UUID")
    return normalized


def _resolve_twin_org_id(
    explicit_org_id: UUID | str | None,
    default_org_id: str | None = None,
) -> str:
    """Resolve and validate the org ID for Digital Twin simulation.

    Priority: explicit_org_id > default_org_id (from system config). The default
    lets single-org installs omit org_id entirely — the LLM then cannot confuse
    org_id with a site_id it saw in a search result.
    """
    resolved = _normalize_optional_uuid(explicit_org_id, "org_id")
    if resolved:
        return resolved
    if default_org_id:
        normalized_default = _normalize_optional_uuid(default_org_id, "org_id")
        if normalized_default:
            return normalized_default
    raise ToolError(
        "org_id is required when action='simulate' and no default org is configured " "(set SystemConfig.mist_org_id)."
    )


def _coerce_action_type(action_type: Action_type | str | None) -> Action_type | None:
    """Normalize action_type to enum with clear ToolError messages."""
    if action_type is None:
        return None
    if isinstance(action_type, Action_type):
        return action_type

    raw = str(action_type).strip().lower()
    if not raw:
        return None
    if is_placeholder(raw):
        raise ToolError("action_type must be a real value (create, update, delete), not a placeholder")

    try:
        return Action_type(raw)
    except ValueError as exc:
        raise ToolError("action_type must be one of: create, update, delete") from exc


def _coerce_object_type(object_type: Object_type | str | None) -> Object_type | None:
    """Normalize object_type to enum with clear ToolError messages."""
    if object_type is None:
        return None
    if isinstance(object_type, Object_type):
        return object_type

    raw = str(object_type).strip().lower()
    if not raw:
        return None
    if is_placeholder(raw):
        raise ToolError("object_type must be a real enum value, not a placeholder")

    try:
        return Object_type(raw)
    except ValueError as exc:
        valid_values = ", ".join(sorted(obj.value for obj in Object_type))
        raise ToolError(f"object_type must be one of: {valid_values}") from exc


def _scope_and_resource(object_type: Object_type) -> tuple[str, str]:
    """Translate enum object_type into endpoint scope/resource parts."""
    value = object_type.value
    if value.startswith("org_"):
        scope = "org"
        resource = value[len("org_") :]
    elif value.startswith("site_"):
        scope = "site"
        resource = value[len("site_") :]
    else:
        raise ToolError(f"Unsupported object_type '{value}'")

    return scope, _OBJECT_RESOURCE_OVERRIDES.get(object_type, resource)


def _build_simulation_write(
    *,
    action_type: Action_type,
    org_id: str,
    site_id: str | None,
    object_type: Object_type,
    payload: dict[str, Any] | None,
    object_id: str | None,
) -> dict[str, Any]:
    """Compile a strict enum-driven change request into one Mist write operation."""
    from app.modules.digital_twin.services.endpoint_parser import parse_endpoint

    scope, resource = _scope_and_resource(object_type)
    method = _ACTION_TO_METHOD[action_type]
    is_singleton = object_type in _SINGLETON_OAS_PATHS

    if scope == "site":
        if not site_id:
            raise ToolError(f"site_id is required when object_type='{object_type.value}'")
    elif site_id:
        raise ToolError(f"site_id is not supported when object_type='{object_type.value}'")

    if is_singleton:
        if action_type != Action_type.UPDATE:
            raise ToolError(
                f"object_type='{object_type.value}' is a singleton — only action_type='update' is supported"
            )
        if object_id:
            raise ToolError(
                f"object_id must not be provided for singleton object_type='{object_type.value}' — "
                "the site_id is the identifier"
            )
    else:
        if action_type in {Action_type.UPDATE, Action_type.DELETE} and not object_id:
            raise ToolError("object_id is required when action_type is 'update' or 'delete'")
        if action_type == Action_type.CREATE and object_id:
            raise ToolError("object_id is not supported when action_type is 'create'")

    if action_type in {Action_type.CREATE, Action_type.UPDATE}:
        if payload is None or not isinstance(payload, dict):
            raise ToolError("payload must be a JSON object when action_type is 'create' or 'update'")
        placeholder_path = _first_payload_placeholder(payload)
        if placeholder_path:
            raise ToolError(
                f"payload contains unresolved placeholders at {placeholder_path}. Replace placeholders with real values before simulation"
            )
    elif payload is not None:
        raise ToolError("payload is not supported when action_type is 'delete'")

    if is_singleton:
        endpoint = _SINGLETON_OAS_PATHS[object_type].format(site_id=site_id)
    else:
        if scope == "org":
            endpoint_base = f"/api/v1/orgs/{org_id}/{resource}"
        else:
            endpoint_base = f"/api/v1/sites/{site_id}/{resource}"

        endpoint = endpoint_base if action_type == Action_type.CREATE else f"{endpoint_base}/{object_id}"

    parsed = parse_endpoint(method, endpoint)
    if parsed.error:
        raise ToolError(f"object_type/action_type combination generated invalid endpoint '{endpoint}': {parsed.error}")
    if parsed.org_id and parsed.org_id != org_id:
        raise ToolError(f"Generated endpoint org_id '{parsed.org_id}' does not match provided org_id '{org_id}'")
    if scope == "site" and parsed.site_id != site_id:
        raise ToolError(f"Generated endpoint site_id '{parsed.site_id}' does not match provided site_id '{site_id}'")

    write: dict[str, Any] = {"method": method, "endpoint": endpoint}
    if payload is not None:
        write["body"] = payload
    return write


def _build_simulation_writes_from_changes(
    *,
    changes: list[dict[str, Any]],
    org_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile a list of change objects into Mist write operations."""
    allowed_fields = {"action_type", "object_type", "site_id", "payload", "object_id"}
    writes: list[dict[str, Any]] = []
    normalized_changes: list[dict[str, Any]] = []

    if not changes:
        raise ToolError("changes must contain at least one change object")
    if len(changes) > _MAX_CHANGES_PER_SIMULATE:
        raise ToolError(
            f"changes list exceeds maximum size of {_MAX_CHANGES_PER_SIMULATE} "
            f"(received {len(changes)}). Split into multiple simulate calls."
        )

    for index, raw_change in enumerate(changes):
        if not isinstance(raw_change, dict):
            raise ToolError(f"changes[{index}] must be an object")

        unknown = sorted(str(key) for key in raw_change.keys() if str(key) not in allowed_fields)
        if unknown:
            raise ToolError(
                f"changes[{index}] contains unsupported field(s): {', '.join(unknown)}. "
                f"Allowed fields: {', '.join(sorted(allowed_fields))}"
            )

        change_action_type = _coerce_action_type(raw_change.get("action_type"))
        if change_action_type is None:
            raise ToolError(f"changes[{index}].action_type is required")

        change_object_type = _coerce_object_type(raw_change.get("object_type"))
        if change_object_type is None:
            raise ToolError(f"changes[{index}].object_type is required")

        change_site_id = _normalize_optional_uuid(raw_change.get("site_id"), f"changes[{index}].site_id")
        change_object_id = _normalize_optional_uuid(raw_change.get("object_id"), f"changes[{index}].object_id")
        change_payload = raw_change.get("payload")
        if change_payload is not None and not isinstance(change_payload, dict):
            raise ToolError(f"changes[{index}].payload must be a JSON object when provided")

        writes.append(
            _build_simulation_write(
                action_type=change_action_type,
                org_id=org_id,
                site_id=change_site_id,
                object_type=change_object_type,
                payload=change_payload,
                object_id=change_object_id,
            )
        )
        normalized_changes.append(
            {
                "action_type": change_action_type.value,
                "object_type": change_object_type.value,
                "site_id": change_site_id,
                "object_id": change_object_id,
            }
        )

    return writes, normalized_changes


def _validate_twin_inputs(
    *,
    action: TwinActionType | str,
    action_type: Action_type | str | None,
    org_id: UUID | str | None,
    site_id: UUID | str | None,
    object_type: Object_type | str | None,
    payload: dict[str, Any] | None,
    object_id: UUID | str | None,
    changes: list[dict[str, Any]] | None = None,
    session_id: str = "",
    default_org_id: str | None = None,
) -> dict[str, Any]:
    """Validate action-specific input coherence for the Digital Twin tool.

    `default_org_id` is the async-resolved system-wide fallback (from
    `SystemConfig.mist_org_id`) used when the caller omits an explicit `org_id`.
    """

    normalized_action = action.value if isinstance(action, TwinActionType) else str(action).strip().lower()
    if normalized_action not in _TWIN_ACTIONS:
        raise ToolError(f"Unknown action '{action}'. Use simulate, approve, reject, status, or history")

    normalized_session_id = session_id.strip()
    if normalized_session_id and is_placeholder(normalized_session_id):
        raise ToolError(f"Invalid session_id '{session_id}': unresolved placeholders are not allowed")
    if normalized_session_id and normalized_action in (_TWIN_SESSION_ACTIONS | {"simulate"}):
        _validate_session_id_format(normalized_session_id)

    normalized_action_type = _coerce_action_type(action_type)
    normalized_object_type = _coerce_object_type(object_type)
    normalized_org_id = _normalize_optional_uuid(org_id, "org_id")
    normalized_site_id = _normalize_optional_uuid(site_id, "site_id")
    normalized_object_id = _normalize_optional_uuid(object_id, "object_id")
    changes_provided = changes is not None
    normalized_changes = changes or []
    if changes is not None and not isinstance(changes, list):
        raise ToolError("changes must be a list of change objects when provided")

    has_simulate_params = any(
        [
            normalized_action_type is not None,
            normalized_org_id is not None,
            normalized_site_id is not None,
            normalized_object_type is not None,
            payload is not None,
            normalized_object_id is not None,
            changes_provided,
        ]
    )

    if normalized_action in _TWIN_SESSION_ACTIONS:
        if not normalized_session_id:
            raise ToolError(f"session_id required for {normalized_action} action")
        if has_simulate_params:
            raise ToolError(
                f"action_type, org_id, site_id, object_type, payload, object_id, and changes are not supported for action='{normalized_action}'"
            )
    elif normalized_action == "history":
        if normalized_session_id:
            raise ToolError("session_id is not supported for action='history'")
        if has_simulate_params:
            raise ToolError(
                "action_type, org_id, site_id, object_type, payload, object_id, and changes are not supported for action='history'"
            )
    else:
        resolved_org_id = _resolve_twin_org_id(normalized_org_id, default_org_id)

        if changes_provided:
            if any(
                [
                    normalized_action_type is not None,
                    normalized_site_id is not None,
                    normalized_object_type is not None,
                    payload is not None,
                    normalized_object_id is not None,
                ]
            ):
                raise ToolError(
                    "changes is mutually exclusive with action_type, site_id, object_type, payload, and object_id"
                )

            writes, requested_changes = _build_simulation_writes_from_changes(
                changes=normalized_changes,
                org_id=resolved_org_id,
            )
        else:
            if normalized_action_type is None:
                raise ToolError("action_type is required when action='simulate'")
            if normalized_object_type is None:
                raise ToolError("object_type is required when action='simulate'")

            simulation_write = _build_simulation_write(
                action_type=normalized_action_type,
                org_id=resolved_org_id,
                site_id=normalized_site_id,
                object_type=normalized_object_type,
                payload=payload,
                object_id=normalized_object_id,
            )
            writes = [simulation_write]
            requested_changes = [
                {
                    "action_type": normalized_action_type.value,
                    "object_type": normalized_object_type.value,
                    "site_id": normalized_site_id,
                    "object_id": normalized_object_id,
                }
            ]

        return {
            "action": normalized_action,
            "writes": writes,
            "session_id": normalized_session_id,
            "org_id": resolved_org_id,
            "action_type": requested_changes[0]["action_type"] if len(requested_changes) == 1 else None,
            "object_type": requested_changes[0]["object_type"] if len(requested_changes) == 1 else None,
            "site_id": normalized_site_id,
            "object_id": normalized_object_id,
            "requested_changes": requested_changes,
        }

    return {
        "action": normalized_action,
        "writes": [],
        "session_id": normalized_session_id,
        "org_id": None,
        "action_type": normalized_action_type.value if normalized_action_type else None,
        "object_type": normalized_object_type.value if normalized_object_type else None,
        "site_id": normalized_site_id,
        "object_id": normalized_object_id,
        "requested_changes": [],
    }


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
async def digital_twin(
    action: Annotated[
        TwinActionType,
        Field(
            description=(
                "Action to perform. Use exactly one of:\n"
                "- simulate: stage one or more config changes and run validation checks (single-change fields or changes list).\n"
                "- approve: execute previously simulated staged writes (requires session_id only).\n"
                "- reject: cancel a previously simulated session (requires session_id only).\n"
                "- status: inspect an existing session report and deployment safety state (requires session_id only).\n"
                "- history: list recent sessions for the current user (no other fields).\n"
                "Always run simulate first and only approve when execution_safe is true."
            )
        ),
    ],
    action_type: Annotated[
        Action_type | None,
        Field(
            description=(
                "Whether the simulation change creates, updates, or deletes an object. "
                "Required when action='simulate'. When updating or deleting, object_id is required."
            ),
            examples=["create", "update", "delete"],
            default=None,
        ),
    ] = None,
    org_id: Annotated[
        UUID | None,
        Field(
            description=(
                "Organization ID. Required when action='simulate' UNLESS the system has a default "
                "org configured (SystemConfig.mist_org_id) — in that case, omit this field and the "
                "tool resolves it automatically. NEVER copy an id from a search result and pass it as "
                "org_id unless the search result explicitly labels it 'org_id'. Search results for "
                "sites/devices/wlans return object-level ids, not org ids; passing a site_id as "
                "org_id will compile a valid-looking write that fails at runtime with a misleading "
                "'site not found in backup' error."
            ),
            examples=["8aa21779-1178-4357-b3e0-42c02b93b870"],
            default=None,
        ),
    ] = None,
    site_id: Annotated[
        UUID | None,
        Field(
            default=None,
            description=(
                "Site ID. Required for simulate when object_type is site-scoped (value starts with 'site_'). "
                "Do not pass site_id for org-scoped object_type values."
            ),
            examples=["2818e386-8dec-4562-9ede-5b8a0fbbdc71"],
        ),
    ] = None,
    object_type: Annotated[
        Object_type | None,
        Field(
            description=(
                "Type of configuration object to create, update, or delete. Required when action='simulate'. "
                "Use one of the explicit enum values (org_* or site_*). "
                f"Org-scoped values: {_ORG_OBJECT_TYPE_VALUES}. "
                f"Site-scoped values: {_SITE_OBJECT_TYPE_VALUES}. "
                "Singletons (no object_id, update only): "
                "'site_info' updates the Site document itself — use this for template bindings "
                "(networktemplate_id, rftemplate_id, gatewaytemplate_id, aptemplate_id, "
                "alarmtemplate_id, sitetemplate_id, secpolicy_id, sitegroup_ids) and site identity "
                "(name, timezone, latlng). 'site_setting' updates the site-level runtime settings "
                "singleton — use this for wireless defaults, DNS/NTP, auto_upgrade, wids/rogue, "
                "switch_mgmt, etc. Do NOT use site_setting for template bindings."
            ),
            examples=["org_wlans", "site_wlans", "site_devices", "site_info", "site_setting"],
            default=None,
        ),
    ] = None,
    payload: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "JSON payload for create/update simulation. Required when action_type is 'create' or 'update'. "
                "When updating an existing object, include all required attributes in the payload. "
                "Recommended workflow: first read the current object via get-configuration tools, then apply only intended changes. "
                "Do not include unresolved placeholders such as {{var}}, {id}, <id>, or :id."
            ),
            examples=[{"ssid": "Guest", "enabled": True, "vlan_id": "200"}],
            default=None,
        ),
    ] = None,
    object_id: Annotated[
        UUID | None,
        Field(
            description=(
                "Object ID for update/delete simulation target. Required when action_type is 'update' or 'delete'."
            ),
            default=None,
            examples=["3c7f19c2-4c16-4f4c-9f1b-8f5338107bd7"],
        ),
    ] = None,
    changes: Annotated[
        list[dict[str, Any]] | None,
        Field(
            description=(
                "Optional multi-change simulate input. When provided (action='simulate' only), pass a list of change objects, "
                "each containing: action_type, object_type, and optional site_id, payload, object_id. "
                "Use this to stage multiple writes in one Digital Twin session. "
                "Mutually exclusive with top-level action_type/site_id/object_type/payload/object_id."
            ),
            examples=[
                [
                    {
                        "action_type": "update",
                        "object_type": "site_wlans",
                        "site_id": "2818e386-8dec-4562-9ede-5b8a0fbbdc71",
                        "object_id": "3c7f19c2-4c16-4f4c-9f1b-8f5338107bd7",
                        "payload": {"ssid": "Guest"},
                    },
                    {
                        "action_type": "update",
                        "object_type": "site_psks",
                        "site_id": "2818e386-8dec-4562-9ede-5b8a0fbbdc71",
                        "object_id": "6c7f19c2-4c16-4f4c-9f1b-8f5338107bd8",
                        "payload": {"name": "Guest-PSK"},
                    },
                ]
            ],
            default=None,
        ),
    ] = None,
    session_id: Annotated[
        str,
        Field(
            description=(
                "Digital Twin session ID for approve/reject/status actions. "
                "For action='simulate', optionally pass an existing session_id to record another remediation iteration. "
                "Format: 24-character hex MongoDB ObjectId."
            ),
            examples=["67f1f77bcf86cd799439011a"],
            default="",
        ),
    ] = "",
    ctx: Context = CurrentContext(),
) -> str:
    """Pre-deployment simulation engine (Digital Twin) for Mist config changes.

    IMPORTANT WORKFLOW:
    1. Call get_configuration_object_schema(object_type, org_id, ...) first to discover required fields
       and get an OAS-derived example payload.
    2. (Optional but cheap) Call validate_configuration_payload(object_type, org_id, payload, ...) to
       dry-validate your draft before burning a twin session.
    3. Call digital_twin(action='simulate', ...) with the validated payload. The response will include
       `execution_safe` and `next_action` — only call action='approve' when execution_safe is true.
    4. Call digital_twin(action='approve', session_id=...) to deploy. Approve is DESTRUCTIVE and writes
       the change to Mist.

        Simulation mode (`action='simulate'`) supports two contracts:
        - Single change contract (backward compatible):
            `action_type`, `org_id`, `object_type`, plus action-specific `site_id`/`payload`/`object_id`
        - Multi-change contract:
            `org_id` + `changes` (list of change objects), where each change object contains
            `action_type`, `object_type`, and action-specific `site_id`/`payload`/`object_id`

    Session mode actions (`approve`, `reject`, `status`, `history`) only require
    session metadata and reject simulation fields to avoid ambiguous calls.

    Calling simulate with an existing `session_id` appends another remediation iteration to that
    session (the prior iterations are preserved; use action='status' to inspect history).

        Required/forbidden matrix:
        - action=simulate (single):
            required: action_type, org_id, object_type
            required when action_type in (create, update): payload
            required when action_type in (update, delete): object_id
            required when object_type starts with site_: site_id
            forbidden: site_id for org_* object_type
        - action=simulate (multi):
            required: org_id, changes (non-empty list)
            each change entry requires: action_type, object_type
            each change entry follows the same create/update/delete requirements as single simulate
            forbidden at top-level when using changes: action_type, site_id, object_type, payload, object_id
        - action in (approve, reject, status):
            required: session_id (24-char hex ObjectId)
            forbidden: action_type, org_id, site_id, object_type, payload, object_id, changes
        - action=history:
            required: none
            forbidden: session_id, action_type, org_id, site_id, object_type, payload, object_id, changes

        Usage examples:
        1) Create org WLAN
             digital_twin(
                 action='simulate',
                 action_type='create',
                 org_id='8aa21779-1178-4357-b3e0-42c02b93b870',
                 object_type='org_wlans',
                 payload={'ssid': 'Guest', 'enabled': True, 'vlan_id': '200'}
             )

        2) Update site WLAN
             digital_twin(
                 action='simulate',
                 action_type='update',
                 org_id='8aa21779-1178-4357-b3e0-42c02b93b870',
                 site_id='2818e386-8dec-4562-9ede-5b8a0fbbdc71',
                 object_type='site_wlans',
                 object_id='3c7f19c2-4c16-4f4c-9f1b-8f5338107bd7',
                 payload={'ssid': 'Guest', 'enabled': True}
             )

        3) Delete site PSK
             digital_twin(
                 action='simulate',
                 action_type='delete',
                 org_id='8aa21779-1178-4357-b3e0-42c02b93b870',
                 site_id='2818e386-8dec-4562-9ede-5b8a0fbbdc71',
                 object_type='site_psks',
                 object_id='3c7f19c2-4c16-4f4c-9f1b-8f5338107bd7'
             )

        4) Approve safe session
             digital_twin(action='approve', session_id='67f1f77bcf86cd799439011a')

        The simulate response ALWAYS includes:
        - session_id, status, overall_severity, remediation_count
        - requested_change: normalized change inputs
        - compiled_write: generated Mist API write (method/endpoint/body)
        - execution_safe (bool): true only when deployment is safe to approve
        - next_action: one of 'approve' | 'fix_and_resimulate' — follow this literally
        If the internal prediction report is missing, execution_safe is false, next_action is
        'fix_and_resimulate', and result includes a 'warning' field explaining the gap.
    """
    _ = ctx

    from beanie import PydanticObjectId

    from app.models.system import SystemConfig
    from app.models.user import User
    from app.modules.digital_twin.services import twin_service

    # Enforce admin role (mirrors REST API require_admin on /digital-twin/*).
    user_id = mcp_user_id_var.get()
    if not user_id:
        raise ToolError("Access denied: user context not available")
    try:
        user_obj_id = PydanticObjectId(user_id)
    except Exception as exc:
        logger.warning("twin_mcp_invalid_user_id", user_id=user_id, error=str(exc))
        raise ToolError("Access denied: invalid user context") from None
    user = await User.get(user_obj_id)
    if not user or "admin" not in user.roles:
        raise ToolError("Access denied: admin role required")

    default_org_id: str | None = None
    try:
        system_config = await SystemConfig.get_config()
        default_org_id = system_config.mist_org_id
    except Exception:
        # SystemConfig lookup failures should not block simulate — the validator
        # still raises a clear ToolError if org_id ends up unresolvable.
        default_org_id = None

    validated = _validate_twin_inputs(
        action=action,
        action_type=action_type,
        org_id=org_id,
        site_id=site_id,
        object_type=object_type,
        payload=payload,
        object_id=object_id,
        changes=changes,
        session_id=session_id,
        default_org_id=default_org_id,
    )

    action_value = validated["action"]
    session_id_value = validated["session_id"]

    if action_value == "simulate":
        write_list = validated["writes"]
        existing_id = session_id_value if session_id_value else None

        client_name: str | None = None
        try:
            client_obj = getattr(ctx, "client", None)
            if client_obj is not None:
                client_name = getattr(client_obj, "name", None)
        except Exception:
            client_name = None

        source_ref = _resolve_source_ref(client_name)

        try:
            session = await twin_service.simulate(
                user_id=user_id,
                org_id=validated["org_id"],
                writes=write_list,
                source="mcp",
                source_ref=source_ref,
                existing_session_id=existing_id,
            )
        except ValueError as exc:
            logger.warning(
                "twin_simulate_failed",
                user_id=user_id,
                org_id=validated["org_id"],
                existing_session_id=existing_id,
                error=str(exc),
            )
            raise ToolError("Simulation failed — check inputs and try again") from exc

        report = session.prediction_report
        result: dict[str, Any] = {
            "session_id": str(session.id),
            "status": session.status.value,
            "overall_severity": session.overall_severity,
            "remediation_count": session.remediation_count,
            "requested_changes": validated["requested_changes"],
            "compiled_writes": write_list,
            # Always populate execution_safe / next_action so LLMs can branch reliably.
            "execution_safe": False,
            "next_action": "fix_and_resimulate",
        }

        # Backward-compatible aliases for existing MCP clients.
        single_change = validated["requested_changes"][0]
        result["requested_change"] = {
            "action_type": single_change["action_type"],
            "object_type": single_change["object_type"],
            "org_id": validated["org_id"],
            "site_id": single_change["site_id"],
            "object_id": single_change["object_id"],
        }
        result["compiled_write"] = write_list[0]

        if report:
            result["summary"] = report.summary
            result["execution_safe"] = report.execution_safe
            result["next_action"] = "approve" if report.execution_safe else "fix_and_resimulate"
            result["counts"] = {
                "total": report.total_checks,
                "passed": report.passed,
                "warnings": report.warnings,
                "errors": report.errors,
                "critical": report.critical,
            }
            result.update(_build_report_diagnostics(report))
        else:
            result["warning"] = "No prediction report generated for this simulation; treat as unsafe until resimulated."

        return to_json(result)

    if action_value == "approve":
        session = await twin_service.get_session(session_id_value)
        if not session:
            raise ToolError(f"Session {session_id_value} not found")
        if str(session.user_id) != user_id:
            logger.warning(
                "twin_session_access_denied",
                session_id=session_id_value,
                requested_by=user_id,
                session_owner=str(session.user_id),
                action="approve",
            )
            raise ToolError(f"Session {session_id_value} not found")

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

        try:
            session = await twin_service.approve_and_execute(session_id_value, user_id=user_id)
        except twin_service.TwinApprovalError as exc:
            logger.warning(
                "twin_approve_failed",
                session_id=session_id_value,
                user_id=user_id,
                code=exc.code.value,
                error=str(exc),
            )
            raise ToolError(_twin_approve_messages().get(exc.code, "Session cannot be approved")) from exc
        except ValueError as exc:
            logger.warning(
                "twin_approve_failed",
                session_id=session_id_value,
                user_id=user_id,
                error=str(exc),
            )
            raise ToolError("Session cannot be approved") from exc
        return to_json(
            {
                "session_id": str(session.id),
                "status": session.status.value,
                "message": "Deployment complete" if session.status.value == "deployed" else "Deployment failed",
            }
        )

    if action_value == "reject":
        try:
            session = await twin_service.reject_session(session_id_value, user_id=user_id)
        except ValueError as exc:
            logger.warning(
                "twin_reject_failed",
                session_id=session_id_value,
                user_id=user_id,
                error=str(exc),
            )
            raise ToolError("Session cannot be rejected") from exc
        return to_json({"session_id": str(session.id), "status": session.status.value})

    if action_value == "status":
        try:
            session = await twin_service.get_session(session_id_value)
        except ValueError as exc:
            logger.warning(
                "twin_status_failed",
                session_id=session_id_value,
                user_id=user_id,
                error=str(exc),
            )
            raise ToolError(f"Session {session_id_value} not found") from exc
        if not session:
            raise ToolError(f"Session {session_id_value} not found")
        if str(session.user_id) != user_id:
            logger.warning(
                "twin_session_access_denied",
                session_id=session_id_value,
                requested_by=user_id,
                session_owner=str(session.user_id),
                action="status",
            )
            raise ToolError(f"Session {session_id_value} not found")

        report = session.prediction_report
        status_result: dict[str, Any] = {
            "session_id": str(session.id),
            "status": session.status.value,
            "severity": session.overall_severity,
            "writes": len(session.staged_writes),
            "remediation_count": session.remediation_count,
            # Always populate execution_safe / next_action for reliable LLM branching.
            "execution_safe": False,
            "next_action": "fix_and_resimulate",
        }
        if report:
            status_result["summary"] = report.summary
            status_result["execution_safe"] = report.execution_safe
            status_result["next_action"] = "approve" if report.execution_safe else "fix_and_resimulate"
            status_result["counts"] = {
                "total": report.total_checks,
                "passed": report.passed,
                "warnings": report.warnings,
                "errors": report.errors,
                "critical": report.critical,
            }
            status_result.update(_build_report_diagnostics(report))
        else:
            status_result["warning"] = "No prediction report on this session; treat as unsafe."

        return to_json(status_result)

    sessions, _total = await twin_service.list_sessions(user_id, limit=10)
    return to_json(
        {
            "sessions": [
                {
                    "id": str(s.id),
                    "status": s.status.value,
                    "severity": s.overall_severity,
                    "execution_safe": s.prediction_report.execution_safe if s.prediction_report else None,
                    "summary": s.prediction_report.summary if s.prediction_report else None,
                    "source": s.source,
                    "writes": len(s.staged_writes),
                    "created_at": s.created_at,
                }
                for s in sessions
            ]
        }
    )

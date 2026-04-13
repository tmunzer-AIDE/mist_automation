"""
Backup tool — consolidated backup operations with action dispatch.

Actions: object_info, version_detail, compare, trigger, restore.
"""

import re
from typing import Annotated, Any

import structlog
from fastmcp import Context
from fastmcp.dependencies import CurrentContext
from fastmcp.exceptions import ToolError
from pydantic import Field

from app.modules.mcp_server.helpers import (
    cap_list,
    elicit_confirmation,
    elicit_restore_confirmation,
    extract_fields,
    prune_config,
    to_json,
    truncate_value,
)
from app.modules.mcp_server.server import mcp
from app.modules.mcp_server.tools.utils import is_placeholder

logger = structlog.get_logger(__name__)

_BACKUP_ACTIONS: set[str] = {
    "object_info",
    "version_detail",
    "compare",
    "trigger",
    "restore",
    "job_detail",
    "job_logs",
}
_BACKUP_TYPES: set[str] = {"full", "manual"}
_LOG_LEVELS: set[str] = {"info", "warning", "error"}
_OBJECT_TYPE_PATTERN = re.compile(r"^(org|site):[a-z0-9_]+$")

# Event types whose captured configuration reflects the actual live state of the object
# (vs. events like 'restored' and 'deleted' that may leave partial or stale config).
_DATA_EVENT_TYPES: set[str] = {"full_backup", "updated", "created", "incremental"}


def _event_type_str(event_type: Any) -> str:
    """Coerce a BackupEventType enum or raw string into its string value."""
    return event_type.value if hasattr(event_type, "value") else str(event_type)


def _is_data_event(event_type: Any) -> bool:
    """Return True when a version's event_type captures the live object configuration."""
    return _event_type_str(event_type) in _DATA_EVENT_TYPES


def _validate_backup_inputs(
    *,
    action: str,
    object_id: str,
    version_id: str,
    version_number: int,
    version_id_1: str,
    version_id_2: str,
    backup_type: str,
    object_type: str,
    site_id: str,
    object_ids: list[str] | None,
    backup_id: str,
    level: str,
) -> dict[str, Any]:
    normalized_action = action.strip().lower()
    if normalized_action not in _BACKUP_ACTIONS:
        raise ToolError(f"Unknown action '{action}'. Use: {', '.join(sorted(_BACKUP_ACTIONS))}")

    normalized_object_id = object_id.strip()
    normalized_version_id = version_id.strip()
    normalized_version_number = version_number if version_number and version_number > 0 else 0
    normalized_version_id_1 = version_id_1.strip()
    normalized_version_id_2 = version_id_2.strip()
    normalized_backup_type = backup_type.strip().lower()
    normalized_object_type = object_type.strip().lower()
    normalized_site_id = site_id.strip()
    normalized_backup_id = backup_id.strip()
    normalized_level = level.strip().lower()
    normalized_object_ids = [oid.strip() for oid in (object_ids or []) if oid and oid.strip()]

    for label, value in (
        ("object_id", normalized_object_id),
        ("version_id", normalized_version_id),
        ("version_id_1", normalized_version_id_1),
        ("version_id_2", normalized_version_id_2),
        ("site_id", normalized_site_id),
        ("backup_id", normalized_backup_id),
    ):
        if value and is_placeholder(value):
            raise ToolError(f"Invalid {label} '{value}': unresolved placeholders are not allowed")

    for oid in normalized_object_ids:
        if is_placeholder(oid):
            raise ToolError(f"Invalid object_ids entry '{oid}': unresolved placeholders are not allowed")

    if normalized_action == "object_info" and not normalized_object_id:
        raise ToolError("object_id is required for action='object_info'")

    if normalized_action == "version_detail" and not normalized_version_id:
        raise ToolError("version_id is required for action='version_detail'")

    if normalized_action == "compare":
        if not normalized_version_id_1 or not normalized_version_id_2:
            raise ToolError("version_id_1 and version_id_2 are required for action='compare'")
        if normalized_version_id_1 == normalized_version_id_2:
            raise ToolError("version_id_1 and version_id_2 must be different")

    if normalized_action == "trigger":
        if normalized_backup_type not in _BACKUP_TYPES:
            raise ToolError("backup_type must be 'full' or 'manual'")

        if normalized_backup_type == "full":
            if normalized_object_type or normalized_site_id or normalized_object_ids:
                raise ToolError(
                    "For backup_type='full', do not pass object_type, site_id, or object_ids"
                )
        else:
            if not normalized_object_type:
                raise ToolError(
                    "object_type is required for manual backups (example: 'org:wlans' or 'site:devices')"
                )
            if not _OBJECT_TYPE_PATTERN.match(normalized_object_type):
                raise ToolError(
                    "object_type must use 'scope:key' format, e.g. 'org:wlans' or 'site:devices'"
                )
            if normalized_object_type.startswith("site:") and not normalized_site_id:
                raise ToolError("site_id is required for site-scoped manual backups")

    if normalized_action == "restore":
        if normalized_version_id and normalized_version_number:
            raise ToolError(
                "Pass either version_id (MongoDB ObjectId) OR version_number (integer), not both."
            )
        if not normalized_version_id and not normalized_version_number:
            raise ToolError(
                "action='restore' requires version_id (MongoDB ObjectId) or version_number + object_id."
            )
        if normalized_version_number and not normalized_object_id:
            raise ToolError(
                "object_id is required when using version_number for action='restore'."
            )

    if normalized_action in {"job_detail", "job_logs"} and not normalized_backup_id:
        raise ToolError(f"backup_id is required for action='{normalized_action}'")

    if normalized_action == "job_logs" and normalized_level and normalized_level not in _LOG_LEVELS:
        raise ToolError(
            f"Invalid level '{level}'. Use: {', '.join(sorted(_LOG_LEVELS))}"
        )

    return {
        "action": normalized_action,
        "object_id": normalized_object_id,
        "version_id": normalized_version_id,
        "version_number": normalized_version_number,
        "version_id_1": normalized_version_id_1,
        "version_id_2": normalized_version_id_2,
        "backup_type": normalized_backup_type,
        "object_type": normalized_object_type,
        "site_id": normalized_site_id,
        "object_ids": normalized_object_ids or None,
        "backup_id": normalized_backup_id,
        "level": normalized_level,
    }


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
async def backup(
    action: Annotated[
        str,
        Field(
            description=(
                "The backup operation to perform.\n\n"
                "READ-ONLY actions (safe, no Mist side effects):\n"
                "- 'object_info': fetch an object's metadata, version history (without config), and dependency graph.\n"
                "    Required: object_id (Mist UUID).\n"
                "- 'version_detail': fetch a specific version's full configuration.\n"
                "    Required: version_id (MongoDB ObjectId from object_info results).\n"
                "    Optional: fields (dot-notation paths to extract only some keys).\n"
                "- 'compare': diff two backup versions side by side (the tool rejects reversed order).\n"
                "    Required: version_id_1 (older), version_id_2 (newer). Both MongoDB ObjectIds.\n"
                "- 'job_detail': job metadata and aggregated failure/warning counts from execution logs.\n"
                "    Required: backup_id (from search(search_type='backup_jobs')).\n"
                "- 'job_logs': browse execution log entries for a backup job.\n"
                "    Required: backup_id. Optional: level ('info'|'warning'|'error'), skip, limit (default 25, max 50).\n\n"
                "WRITE actions (mutate Mist state; require 'backup' or 'admin' role; always confirm with user):\n"
                "- 'trigger': start a new backup job. Asks user for confirmation.\n"
                "    Required: backup_type. For backup_type='full': no other params. "
                "For backup_type='manual': also object_type (e.g. 'org:wlans') and site_id when site-scoped.\n"
                "- 'restore': restore an object to a specific backup version. Auto-shows a diff card and asks for confirmation.\n"
                "    Required: EXACTLY ONE of version_id (MongoDB ObjectId) OR (version_number + object_id)."
            ),
        ),
    ],
    object_id: Annotated[
        str,
        Field(
            description=(
                "Mist object UUID. Used by action='object_info' to look up all versions of an object, "
                "and by action='restore' when version_number is provided instead of version_id."
            ),
        default="",
        ),
    ]="",
    version_id: Annotated[
        str,
        Field(
            description=(
                "Backup version MongoDB ObjectId (from 'version_id' in object_info results). "
                "Used by action='version_detail' and action='restore'. "
                "For action='restore', pass EITHER version_id OR (version_number + object_id), not both."
            ),
        default="",
        ),
    ]="",
    version_number: Annotated[
        int,
        Field(
            description=(
                "Integer version number from the object's history (1, 2, 3, ...). "
                "ONLY used by action='restore' as an alternative to version_id. "
                "When set, object_id is required and version_id must be empty."
            ),
            ge=0,
        default=0,
        ),
    ]=0,
    version_id_1: Annotated[
        str,
        Field(
            description=(
                "First (OLDER) version MongoDB ObjectId. Used by action='compare'. "
                "Must be older than version_id_2; the tool rejects reversed order."
            ),
        default="",
        ),
    ]="",
    version_id_2: Annotated[
        str,
        Field(
            description=(
                "Second (NEWER) version MongoDB ObjectId. Used by action='compare'. "
                "Must be newer than version_id_1."
            ),
        default="",
        ),
    ]="",
    fields: Annotated[
        list[str]|None,
        Field(
            description=(
                "Dot-notation config paths to extract (e.g. ['ssid', 'auth.type']). "
                "Used by action='version_detail' to return only specific fields instead of the full config."
            ),
        default=None,
        ),
    ]=None,
    backup_type: Annotated[
        str,
        Field(
            description=(
                "Backup type for action='trigger'. One of: "
                "'full' (entire organization; no other params), "
                "'manual' (specific objects; requires object_type)."
            ),
        default="",
        ),
    ]="",
    object_type: Annotated[
        str,
        Field(
            description=(
                "Object type in 'scope:key' format. Required for action='trigger' with backup_type='manual'. "
                "Examples: 'org:wlans', 'org:networks', 'org:devices', 'org:networktemplates', "
                "'org:gatewaytemplates', 'site:devices', 'site:wlans', 'site:settings'. "
                "Use search(search_type='backup_objects', object_type='info') to discover valid keys."
            ),
        default="",
        ),
    ]="",
    site_id: Annotated[
        str,
        Field(
            description=(
                "Mist site UUID. Required when object_type starts with 'site:' for action='trigger' "
                "with backup_type='manual'."
            ),
        default="",
        ),
    ]="",
    object_ids: Annotated[
        list[str]|None,
        Field(
            description=(
                "Specific Mist object UUIDs to back up. Used by action='trigger' with backup_type='manual'. "
                "Omit to back up all objects of object_type."
            ),
        default=None,
        ),
    ]=None,
    backup_id: Annotated[
        str,
        Field(
            description=(
                "BackupJob MongoDB ObjectId. Required for action='job_detail' and action='job_logs'. "
                "Get this from search(search_type='backup_jobs') results."
            ),
        default="",
        ),
    ]="",
    level: Annotated[
        str,
        Field(
            description=(
                "Log level filter for action='job_logs'. One of: 'info', 'warning', 'error'. "
                "Omit to return all levels."
            ),
        default="",
        ),
    ]="",
    skip: Annotated[
        int,
        Field(
            description="Pagination offset for action='job_logs' (0-based).",
            ge=0,
        default=0,
            ),
    ]=0,
    limit: Annotated[
        int,
        Field(
            description="Max log entries to return for action='job_logs' (1-50).",
            ge=1,
            le=50,
        default=25,
        ),
    ]=25,
    ctx: Context = CurrentContext(),
) -> str:
    """Manage Mist configuration backups: inspect versioned snapshots, diff versions, trigger backups, or restore.

    Typical READ workflow:
    1. Use search(search_type='backup_objects', object_type=..., query=...) to find an object.
    2. Use backup(action='object_info', object_id=...) to list all versions.
    3. Use backup(action='version_detail', version_id=...) or backup(action='compare', ...) to inspect.

    WRITE actions (trigger, restore) require the 'backup' or 'admin' role and always prompt the user
    for confirmation via elicitation. Restore auto-computes a diff and shows a rich diff card before
    executing.
    """
    validated = _validate_backup_inputs(
        action=action,
        object_id=object_id,
        version_id=version_id,
        version_number=version_number,
        version_id_1=version_id_1,
        version_id_2=version_id_2,
        backup_type=backup_type,
        object_type=object_type,
        site_id=site_id,
        object_ids=object_ids,
        backup_id=backup_id,
        level=level,
    )

    dispatchers: dict[str, Any] = {
        "object_info": _object_info,
        "version_detail": _version_detail,
        "compare": _compare,
        "trigger": _trigger,
        "restore": _restore,
        "job_detail": _job_detail,
        "job_logs": _job_logs,
    }

    handler = dispatchers[validated["action"]]

    return await handler(
        ctx=ctx,
        object_id=validated["object_id"],
        version_id=validated["version_id"],
        version_number=validated["version_number"],
        version_id_1=validated["version_id_1"],
        version_id_2=validated["version_id_2"],
        fields=fields,
        backup_type=validated["backup_type"],
        object_type=validated["object_type"],
        site_id=validated["site_id"],
        object_ids=validated["object_ids"],
        backup_id=validated["backup_id"],
        level=validated["level"],
        skip=skip,
        limit=limit,
    )


async def _object_info(*, object_id: str, **_kwargs) -> str:
    """Get backup object metadata, version history, and dependencies."""

    from app.modules.backup.models import BackupObject

    versions = await BackupObject.find(BackupObject.object_id == object_id).sort(-BackupObject.version).to_list()
    if not versions:
        raise ToolError(f"No backup found for object_id '{object_id}'")

    latest = versions[0]

    # Build version list (no configuration) with event-type semantics.
    version_list: list[dict[str, Any]] = []
    latest_data_version: BackupObject | None = None
    for v in versions:
        event_type_value = _event_type_str(v.event_type)
        is_data_event = _is_data_event(v.event_type)
        if is_data_event and latest_data_version is None:
            latest_data_version = v
        version_list.append(
            {
                "version_id": str(v.id),
                "version": v.version,
                "event_type": event_type_value,
                "is_data_event": is_data_event,
                "changed_fields": v.changed_fields[:10] if v.changed_fields else [],
                "backed_up_at": v.backed_up_at,
            }
        )

    # Dependencies from latest version references
    parents = []
    for ref in latest.references or []:
        parents.append({"type": ref.target_type, "id": ref.target_id, "field_path": ref.field_path})

    # Reverse-lookup children: objects that reference this object
    children_cursor = BackupObject.find(
        {"references.target_id": object_id, "is_deleted": False},
    ).sort("-version")
    child_docs = await children_cursor.to_list()
    seen_children: set[str] = set()
    children = []
    for doc in child_docs:
        if doc.object_id not in seen_children:
            seen_children.add(doc.object_id)
            children.append({"type": doc.object_type, "id": doc.object_id, "name": doc.object_name or ""})

    latest_event_type = _event_type_str(latest.event_type)
    latest_is_data = _is_data_event(latest.event_type)

    result: dict[str, Any] = {
        "object_type": latest.object_type,
        "object_name": latest.object_name,
        "object_id": latest.object_id,
        "site_id": latest.site_id,
        "is_deleted": latest.is_deleted,
        "versions": cap_list(version_list, 30),
        "parents": parents[:20],
        "children": children[:20],
    }

    # Point the LLM at the right version for config inspection. When the latest version
    # is NOT a data event (e.g. 'restored', 'deleted'), its configuration may be partial
    # or stale — recommend the most recent full_backup/updated version instead.
    if latest_data_version is not None:
        result["recommended_version_for_inspection"] = {
            "version_id": str(latest_data_version.id),
            "version": latest_data_version.version,
            "event_type": (
                latest_data_version.event_type.value
                if hasattr(latest_data_version.event_type, "value")
                else str(latest_data_version.event_type)
            ),
            "reason": (
                "Most recent full_backup/updated/created version with full captured config. "
                "Pass this version_id to backup(action='version_detail', ...) to inspect the object's "
                "actual configuration."
                if not latest_is_data
                else "Most recent data-event version. Safe to pass to backup(action='version_detail', ...) "
                "for config inspection."
            ),
        }
    if not latest_is_data:
        result["note"] = (
            f"The latest version (v{latest.version}) is a '{latest_event_type}' event and its "
            "captured configuration may be incomplete. Use recommended_version_for_inspection.version_id "
            "when you need the object's actual current configuration."
        )

    return to_json(result)


async def _version_detail(*, version_id: str, fields: list[str] | None, **_kwargs) -> str:
    """Get a specific backup version's configuration."""
    from beanie import PydanticObjectId

    from app.modules.backup.models import BackupObject

    try:
        obj = await BackupObject.get(PydanticObjectId(version_id))
    except Exception as exc:
        raise ToolError(
            f"Invalid version_id '{version_id}': not a valid 24-char hex MongoDB ObjectId."
        ) from exc

    if not obj:
        raise ToolError(f"Version '{version_id}' not found")

    raw_config = obj.configuration or {}
    top_level_keys = sorted(raw_config.keys()) if isinstance(raw_config, dict) else []
    event_type_value = _event_type_str(obj.event_type)
    is_data_event = _is_data_event(obj.event_type)

    if fields:
        config = extract_fields(raw_config, fields)
    else:
        # On data events, auto-expand the top-level segments of changed_fields so the LLM
        # sees what actually changed on the first call (e.g. 'port_config.ge-0/0/8' →
        # expand 'port_config' fully). changed_fields is empty on restore/deleted events.
        inline_keys: set[str] | None = None
        if is_data_event and obj.changed_fields:
            inline_keys = {f.split(".")[0] for f in obj.changed_fields if f}
        config = prune_config(raw_config, inline_keys=inline_keys)

    result: dict[str, Any] = {
        "version_id": str(obj.id),
        "object_type": obj.object_type,
        "object_name": obj.object_name,
        "object_id": obj.object_id,
        "version": obj.version,
        "event_type": event_type_value,
        "is_data_event": is_data_event,
        "backed_up_at": obj.backed_up_at,
        "configuration": config,
    }

    # Diagnostics: when `fields` was requested but extraction returned nothing, tell the LLM
    # why. Either the path doesn't exist in this version (common for 'restored' events that
    # captured a partial config) or the raw config is empty.
    if fields and not config:
        # Look up the latest data-event version so the LLM can retry against a version with
        # full captured config.
        latest_data_version = (
            await BackupObject.find(
                BackupObject.object_id == obj.object_id,
                {"event_type": {"$in": sorted(_DATA_EVENT_TYPES)}},
            )
            .sort(-BackupObject.version)
            .first_or_none()
        )
        hint_parts = [
            "Field extraction returned no matches.",
            f"Requested fields: {fields}.",
            f"Available top-level keys in this version: {top_level_keys[:30]}"
            + ("..." if len(top_level_keys) > 30 else ""),
        ]
        if not is_data_event:
            hint_parts.append(
                f"This version is a '{event_type_value}' event whose captured configuration may be "
                "partial or stale."
            )
        if latest_data_version is not None and str(latest_data_version.id) != str(obj.id):
            hint_parts.append(
                f"Try version_id='{latest_data_version.id}' "
                f"(version {latest_data_version.version}, event_type="
                f"{latest_data_version.event_type.value if hasattr(latest_data_version.event_type, 'value') else latest_data_version.event_type}) "
                "which was the most recent data event for this object."
            )
        result["diagnostic"] = " ".join(hint_parts)
        result["available_top_level_keys"] = top_level_keys

    return to_json(result)


async def _compare(*, version_id_1: str, version_id_2: str, **_kwargs) -> str:
    """Compare two backup versions and return the diff."""
    from beanie import PydanticObjectId

    from app.modules.backup.models import BackupObject
    from app.modules.backup.utils import deep_diff

    try:
        v1 = await BackupObject.get(PydanticObjectId(version_id_1))
        v2 = await BackupObject.get(PydanticObjectId(version_id_2))
    except Exception as exc:
        raise ToolError("Invalid version ID format") from exc

    if not v1 or not v2:
        raise ToolError("One or both versions not found")

    # Fail loudly on reversed order instead of silently swapping, so the LLM doesn't
    # get a diff labeled "old → new" that's actually "new → old".
    if v1.version > v2.version:
        raise ToolError(
            "version_id_1 must be the OLDER version. You passed them reversed "
            f"(v1.version={v1.version} > v2.version={v2.version}). Swap them and retry."
        )

    diff_entries = deep_diff(v1.configuration, v2.configuration)

    # Truncate diff entries for compactness
    capped = diff_entries[:50]
    for entry in capped:
        for key in ("old", "new", "value"):
            if key in entry:
                entry[key] = truncate_value(entry[key], 200)

    added = sum(1 for e in diff_entries if e.get("type") == "added")
    removed = sum(1 for e in diff_entries if e.get("type") == "removed")
    modified = sum(1 for e in diff_entries if e.get("type") == "modified")

    return to_json(
        {
            "object_type": v2.object_type,
            "object_name": v2.object_name,
            "old_version": v1.version,
            "new_version": v2.version,
            "changes": capped,
            "summary": {"added": added, "removed": removed, "modified": modified, "total": len(diff_entries)},
        }
    )


async def _trigger(
    *, ctx: Context, backup_type: str, object_type: str, site_id: str, object_ids: list[str] | None, **_kwargs
) -> str:
    """Trigger a configuration backup with elicitation for confirmation."""
    from beanie import PydanticObjectId

    from app.core.tasks import create_background_task
    from app.models.system import SystemConfig
    from app.models.user import User
    from app.modules.mcp_server.server import mcp_user_id_var

    # Enforce backup role (mirrors REST API require_backup_role)
    user_id = mcp_user_id_var.get()
    if user_id:
        user = await User.get(PydanticObjectId(user_id))
        if not user or not ("backup" in user.roles or "admin" in user.roles):
            raise ToolError("Access denied: backup role required")
    else:
        raise ToolError("Access denied: user context not available")

    if backup_type not in ("full", "manual"):
        raise ToolError("backup_type must be 'full' or 'manual'")

    if backup_type == "manual" and not object_type:
        raise ToolError("object_type is required for manual backups (e.g., 'org:wlans')")

    config = await SystemConfig.get_config()
    if not config or not config.mist_org_id:
        raise ToolError("Mist Organization ID not configured")

    # Build confirmation description
    if backup_type == "full":
        description = "Trigger a full organization backup?"
    else:
        ids_note = f" ({len(object_ids)} objects)" if object_ids else ""
        description = f"Trigger manual backup of {object_type}{ids_note}?"

    # Elicit confirmation
    await elicit_confirmation(ctx, description)

    # Start backup in background (BackupService manages its own job lifecycle)
    from app.modules.backup.services.backup_service import BackupService
    from app.services.mist_service_factory import create_mist_service

    async def _run_backup() -> dict:
        service = BackupService(await create_mist_service())
        if backup_type == "full":
            return await service.perform_full_backup()
        return await service.perform_manual_backup(
            object_type=object_type, object_ids=object_ids, site_id=site_id or None
        )

    create_background_task(_run_backup(), name=f"mcp-backup-{backup_type}")

    return to_json({"backup_type": backup_type, "status": "started", "message": "Backup started in background."})


async def _restore(
    *,
    ctx: Context,
    version_id: str,
    version_number: int,
    object_id: str = "",
    **_kwargs,
) -> str:
    """Restore an object to a specific backup version with auto-diff elicitation."""
    from beanie import PydanticObjectId

    from app.models.user import User
    from app.modules.backup.models import BackupObject
    from app.modules.backup.utils import deep_diff
    from app.modules.mcp_server.server import mcp_user_id_var

    # Enforce backup role (mirrors REST API require_backup_role)
    user_id = mcp_user_id_var.get()
    if not user_id:
        raise ToolError("Access denied: user context not available")
    user = await User.get(PydanticObjectId(user_id))
    if not user or not ("backup" in user.roles or "admin" in user.roles):
        raise ToolError("Access denied: backup role required")

    # Load target version — caller gives us exactly one of version_id (ObjectId) or version_number + object_id.
    target = None
    if version_id:
        try:
            target = await BackupObject.get(PydanticObjectId(version_id))
        except Exception as exc:
            raise ToolError(
                f"Invalid version_id '{version_id}': not a valid 24-char hex MongoDB ObjectId."
            ) from exc
        if not target:
            raise ToolError(f"Version '{version_id}' not found.")
    else:
        # version_number path — _validate_backup_inputs already enforced object_id is present.
        target = await BackupObject.find_one(
            BackupObject.object_id == object_id,
            BackupObject.version == version_number,
        )
        if not target:
            raise ToolError(
                f"Version {version_number} not found for object_id '{object_id}'. "
                "Use backup(action='object_info', object_id=...) to list valid versions."
            )

    # Find current (latest non-deleted) version of the same object
    current = (
        await BackupObject.find(
            BackupObject.object_id == target.object_id,
            BackupObject.is_deleted == False,  # noqa: E712
        )
        .sort("-version")
        .first_or_none()
    )

    # Compute diff
    is_deleted = current is None
    if is_deleted:
        # Object was deleted — show full target config as "added"
        diff_entries = [{"path": k, "type": "added", "value": v} for k, v in (target.configuration or {}).items()]
    else:
        # Diff: current → target (what will change)
        diff_entries = deep_diff(current.configuration or {}, target.configuration or {})

    # Cap and truncate for the frontend payload
    capped = diff_entries[:50]
    for entry in capped:
        for key in ("old", "new", "value"):
            if key in entry:
                entry[key] = truncate_value(entry[key], 200)

    added = sum(1 for e in diff_entries if e.get("type") == "added")
    removed = sum(1 for e in diff_entries if e.get("type") == "removed")
    modified = sum(1 for e in diff_entries if e.get("type") == "modified")

    # Create restore service once — reused for dry-run and real restore
    from app.modules.backup.services.restore_service import RestoreService
    from app.services.mist_service_factory import create_mist_service

    restore_service = RestoreService(await create_mist_service())
    assert target.id is not None  # always set on fetched documents

    # Run dry-run validation for warnings
    warnings: list[str] = []
    deleted_dependencies: list[dict] = []
    deleted_children: list[dict] = []
    try:
        dry_run_result = await restore_service.restore_object(
            backup_id=target.id,
            dry_run=True,
            restored_by=user.email,
        )
        warnings = dry_run_result.get("warnings", [])
        deleted_dependencies = dry_run_result.get("deleted_dependencies", [])
        deleted_children = dry_run_result.get("deleted_children", [])
    except Exception as exc:
        logger.warning("restore_dry_run_failed", error=str(exc))
        warnings.append("Restore pre-validation failed")

    # Build description
    if is_deleted:
        description = (
            f"Restore deleted {target.object_type} '{target.object_name or target.object_id}' "
            f"from version {target.version}? The object will be recreated."
        )
    elif not diff_entries:
        description = (
            f"Restore {target.object_type} '{target.object_name or target.object_id}' "
            f"to version {target.version}? This version is identical to the current configuration."
        )
    else:
        description = (
            f"Restore {target.object_type} '{target.object_name or target.object_id}' "
            f"to version {target.version}? "
            f"{added} added, {removed} removed, {modified} modified fields."
        )

    # Send rich elicitation with diff data
    diff_data = {
        "object_type": target.object_type,
        "object_name": target.object_name,
        "object_id": target.object_id,
        "target_version": target.version,
        "target_version_id": str(target.id),
        "current_version": current.version if current else None,
        "current_version_id": str(current.id) if current else None,
        "is_deleted": is_deleted,
        "changes": capped,
        "summary": {"added": added, "removed": removed, "modified": modified, "total": len(diff_entries)},
        "warnings": warnings,
        "deleted_dependencies": deleted_dependencies,
        "deleted_children": deleted_children,
    }

    await elicit_restore_confirmation(ctx, description, diff_data)

    # User accepted — execute restore
    try:
        result = await restore_service.restore_object(
            backup_id=target.id,
            dry_run=False,
            restored_by=user.email,
        )

        return to_json(
            {
                "status": result.get("status", "success"),
                "object_type": target.object_type,
                "object_name": target.object_name,
                "object_id": result.get("object_id", target.object_id),
                "version_restored": target.version,
                "message": f"Successfully restored {target.object_type} '{target.object_name}' to version {target.version}.",
            }
        )
    except Exception as exc:
        logger.error("mcp_restore_failed", error=str(exc))
        raise ToolError("Restore operation failed") from exc


async def _job_detail(*, backup_id: str, **_kwargs) -> str:
    """Get backup job metadata and aggregated failure/warning summary from execution logs."""
    from beanie import PydanticObjectId

    from app.modules.backup.models import BackupJob, BackupLogEntry

    try:
        job = await BackupJob.get(PydanticObjectId(backup_id))
    except Exception as exc:
        raise ToolError(f"Invalid backup_id '{backup_id}'") from exc
    if not job:
        raise ToolError(f"Backup job '{backup_id}' not found")

    job_oid = job.id
    agg = await BackupLogEntry.aggregate(
        [
            {"$match": {"backup_job_id": job_oid, "level": {"$in": ["error", "warning"]}}},
            {
                "$facet": {
                    "by_level": [{"$group": {"_id": "$level", "count": {"$sum": 1}}}],
                    "by_phase": [
                        {"$match": {"level": "error"}},
                        {"$group": {"_id": "$phase", "count": {"$sum": 1}}},
                    ],
                    "by_object_type": [
                        {"$match": {"level": "error", "object_type": {"$ne": None}}},
                        {"$group": {"_id": "$object_type", "count": {"$sum": 1}}},
                    ],
                }
            },
        ]
    ).to_list()

    row = agg[0] if agg else {}
    level_counts = {r["_id"]: r["count"] for r in row.get("by_level", [])}
    phase_counts = {r["_id"]: r["count"] for r in row.get("by_phase", [])}
    type_counts = {r["_id"]: r["count"] for r in row.get("by_object_type", [])}

    return to_json(
        {
            "job_id": str(job.id),
            "backup_type": job.backup_type.value if hasattr(job.backup_type, "value") else str(job.backup_type),
            "status": job.status.value if hasattr(job.status, "value") else str(job.status),
            "org_name": job.org_name,
            "site_name": job.site_name,
            "object_count": job.object_count,
            "error": job.error,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "failure_summary": {
                "errors": level_counts.get("error", 0),
                "warnings": level_counts.get("warning", 0),
                "errors_by_phase": phase_counts,
                "errors_by_object_type": type_counts,
            },
        }
    )


async def _job_logs(*, backup_id: str, level: str, skip: int, limit: int, **_kwargs) -> str:
    """Browse execution log entries for a specific backup job."""
    from beanie import PydanticObjectId

    from app.modules.backup.models import BackupLogEntry

    try:
        job_oid = PydanticObjectId(backup_id)
    except Exception as exc:
        raise ToolError(f"Invalid backup_id '{backup_id}'") from exc

    match: dict = {"backup_job_id": job_oid}
    if level:
        match["level"] = level

    limit = min(limit, 50)
    results = await BackupLogEntry.aggregate(
        [
            {"$match": match},
            {
                "$facet": {
                    "total": [{"$count": "n"}],
                    "entries": [{"$sort": {"timestamp": 1}}, {"$skip": skip}, {"$limit": limit}],
                }
            },
        ]
    ).to_list()

    row = results[0] if results else {}
    total = row.get("total", [{}])[0].get("n", 0) if row.get("total") else 0

    return to_json(
        {
            "total": total,
            "skip": skip,
            "limit": limit,
            "entries": [
                {
                    "timestamp": e.get("timestamp"),
                    "level": e.get("level"),
                    "phase": e.get("phase"),
                    "message": e.get("message"),
                    "object_type": e.get("object_type"),
                    "object_id": e.get("object_id"),
                    "object_name": e.get("object_name"),
                }
                for e in row.get("entries", [])
            ],
        }
    )

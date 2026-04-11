"""
Backup tool — consolidated backup operations with action dispatch.

Actions: object_info, version_detail, compare, trigger, restore.
"""

import re
from typing import Annotated, Any

import structlog
from fastmcp import Context
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


def _validate_backup_inputs(
    *,
    action: str,
    object_id: str,
    version_id: str,
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
        if not normalized_version_id:
            raise ToolError("version_id is required for action='restore'")
        if normalized_version_id.isdigit() and not normalized_object_id:
            raise ToolError(
                "When version_id is a numeric version number, object_id is required for action='restore'"
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
        "version_id_1": normalized_version_id_1,
        "version_id_2": normalized_version_id_2,
        "backup_type": normalized_backup_type,
        "object_type": normalized_object_type,
        "site_id": normalized_site_id,
        "object_ids": normalized_object_ids or None,
        "backup_id": normalized_backup_id,
        "level": normalized_level,
    }


@mcp.tool()
async def backup(
    ctx: Context,
    action: Annotated[
        str,
        Field(
            description=(
                "The backup operation to perform. One of:\n"
                "- 'object_info': Get a backed-up object's metadata, full version history (without config), "
                "and dependency graph. Requires: object_id (Mist UUID).\n"
                "- 'version_detail': Get a specific version's full configuration. "
                "Requires: version_id (MongoDB document ID from object_info results). "
                "Optional: fields (list of dot-notation paths to extract specific config keys).\n"
                "- 'compare': Diff two backup versions side by side. "
                "Requires: version_id_1, version_id_2 (MongoDB document IDs from object_info).\n"
                "- 'trigger': Start a backup job (asks user for confirmation). "
                "Requires: backup_type ('full' or 'manual'). "
                "For manual: also requires object_type (e.g. 'org:wlans', 'site:devices').\n"
                "- 'restore': Restore an object to a specific backup version. "
                "Automatically shows the user a diff of what will change and asks for confirmation. "
                "Requires: version_id (MongoDB document ID or version number). "
                "If using a version number, also provide object_id (Mist UUID).\n"
                "- 'job_detail': Get backup job metadata and aggregated failure/warning counts from "
                "execution logs, broken down by phase and object type. Use this to drill into a "
                "specific backup run after finding it via search(type='backup_jobs'). Requires: backup_id.\n"
                "- 'job_logs': Browse execution log entries for a specific backup job, useful for "
                "reading exact error messages. Requires: backup_id. "
                "Optional: level ('info'|'warning'|'error'), skip, limit (default 25, max 50)."
            ),
        ),
    ],
    object_id: Annotated[
        str,
        Field(description="Mist object UUID. Used by action='object_info' to look up all versions of an object."),
    ] = "",
    version_id: Annotated[
        str,
        Field(
            description="Backup version identifier. Used by action='version_detail' and action='restore'. Can be a MongoDB document ID (from 'version_id' in object_info results) or a version number (requires object_id too)."
        ),
    ] = "",
    version_id_1: Annotated[
        str,
        Field(description="First (older) version MongoDB document ID. Used by action='compare'."),
    ] = "",
    version_id_2: Annotated[
        str,
        Field(description="Second (newer) version MongoDB document ID. Used by action='compare'."),
    ] = "",
    fields: Annotated[
        list[str] | None,
        Field(
            description="Dot-notation config paths to extract (e.g. ['ssid', 'auth.type']). Used by action='version_detail' to return only specific fields instead of the full config."
        ),
    ] = None,
    backup_type: Annotated[
        str,
        Field(description="Backup type for action='trigger': 'full' (entire org) or 'manual' (specific objects)."),
    ] = "",
    object_type: Annotated[
        str,
        Field(
            description="Object type in 'scope:key' format (e.g. 'org:wlans', 'site:devices'). Required for action='trigger' with backup_type='manual'."
        ),
    ] = "",
    site_id: Annotated[
        str,
        Field(description="Mist site UUID for site-scoped manual backups. Used by action='trigger'."),
    ] = "",
    object_ids: Annotated[
        list[str] | None,
        Field(description="Specific Mist object UUIDs to back up. Used by action='trigger' with backup_type='manual'."),
    ] = None,
    backup_id: Annotated[
        str,
        Field(
            description="BackupJob MongoDB document ID. Required for action='job_detail' and action='job_logs'. Get this from search(type='backup_jobs') results."
        ),
    ] = "",
    level: Annotated[
        str,
        Field(
            description="Log level filter for action='job_logs'. One of: 'info', 'warning', 'error'. Omit to return all levels."
        ),
    ] = "",
    skip: Annotated[
        int,
        Field(description="Pagination offset for action='job_logs'.", ge=0),
    ] = 0,
    limit: Annotated[
        int,
        Field(description="Max log entries to return for action='job_logs' (1-50).", ge=1, le=50),
    ] = 25,
) -> str:
    """Manage Mist configuration backups: inspect versioned config snapshots, compare changes between versions, or trigger new backups.

    Each backed-up object has a version history. Use 'object_info' first to see all versions,
    then 'version_detail' or 'compare' with the version_ids from the results.
    """
    validated = _validate_backup_inputs(
        action=action,
        object_id=object_id,
        version_id=version_id,
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

    # Build version list (no configuration)
    version_list = [
        {
            "version_id": str(v.id),
            "version": v.version,
            "event_type": v.event_type.value if hasattr(v.event_type, "value") else str(v.event_type),
            "changed_fields": v.changed_fields[:10] if v.changed_fields else [],
            "backed_up_at": v.backed_up_at,
        }
        for v in versions
    ]

    # Dependencies from latest version references
    parents = []
    for ref in latest.references or []:
        parents.append({"type": ref.target_type, "id": ref.target_id, "field_path": ref.field_path})

    # Reverse-lookup children: objects that reference this object
    children_cursor = BackupObject.find(
        {"references.target_id": object_id, "is_deleted": False},
    ).sort(-BackupObject.version)
    child_docs = await children_cursor.to_list()
    seen_children: set[str] = set()
    children = []
    for doc in child_docs:
        if doc.object_id not in seen_children:
            seen_children.add(doc.object_id)
            children.append({"type": doc.object_type, "id": doc.object_id, "name": doc.object_name or ""})

    return to_json(
        {
            "object_type": latest.object_type,
            "object_name": latest.object_name,
            "object_id": latest.object_id,
            "site_id": latest.site_id,
            "is_deleted": latest.is_deleted,
            "versions": cap_list(version_list, 30),
            "parents": parents[:20],
            "children": children[:20],
        }
    )


async def _version_detail(*, version_id: str, fields: list[str] | None, **_kwargs) -> str:
    """Get a specific backup version's configuration."""
    from beanie import PydanticObjectId

    from app.modules.backup.models import BackupObject

    try:
        obj = await BackupObject.get(PydanticObjectId(version_id))
    except Exception as exc:
        raise ToolError(f"Invalid version_id '{version_id}'") from exc

    if not obj:
        raise ToolError(f"Version '{version_id}' not found")

    config = obj.configuration or {}
    if fields:
        config = extract_fields(config, fields)
    else:
        config = prune_config(config)

    return to_json(
        {
            "version_id": str(obj.id),
            "object_type": obj.object_type,
            "object_name": obj.object_name,
            "object_id": obj.object_id,
            "version": obj.version,
            "event_type": obj.event_type.value if hasattr(obj.event_type, "value") else str(obj.event_type),
            "backed_up_at": obj.backed_up_at,
            "configuration": config,
        }
    )


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

    # Ensure v1 is older
    if v1.version > v2.version:
        v1, v2 = v2, v1

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


async def _restore(*, ctx: Context, version_id: str, object_id: str = "", **_kwargs) -> str:
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

    # Load target version — accept either MongoDB ObjectId or version number
    target = None
    try:
        target = await BackupObject.get(PydanticObjectId(version_id))
    except Exception:
        # Not a valid ObjectId — try as a version number with object_id
        try:
            version_num = int(version_id)
            if object_id:
                target = await BackupObject.find_one(
                    BackupObject.object_id == object_id,
                    BackupObject.version == version_num,
                )
        except (ValueError, TypeError):
            pass
    if not target:
        hint = " Provide either a MongoDB document ID or a version number with object_id."
        raise ToolError(f"Version '{version_id}' not found.{hint}")

    # Find current (latest non-deleted) version of the same object
    current = (
        await BackupObject.find(
            BackupObject.object_id == target.object_id,
            BackupObject.is_deleted == False,  # noqa: E712
        )
        .sort(-BackupObject.version)
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

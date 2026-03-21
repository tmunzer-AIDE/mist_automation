"""
Backup tool — consolidated backup operations with action dispatch.

Actions: object_info, version_detail, compare, trigger.
"""

from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from app.modules.mcp_server.helpers import (
    cap_list,
    elicit_confirmation,
    extract_fields,
    prune_config,
    to_json,
    truncate_value,
)
from app.modules.mcp_server.server import mcp


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
                "For manual: also requires object_type (e.g. 'org:wlans', 'site:devices')."
            ),
        ),
    ],
    object_id: Annotated[
        str,
        Field(description="Mist object UUID. Used by action='object_info' to look up all versions of an object."),
    ] = "",
    version_id: Annotated[
        str,
        Field(description="MongoDB document ID of a specific backup version. Used by action='version_detail'. Get this from the 'versions' array in object_info results."),
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
        Field(description="Dot-notation config paths to extract (e.g. ['ssid', 'auth.type']). Used by action='version_detail' to return only specific fields instead of the full config."),
    ] = None,
    backup_type: Annotated[
        str,
        Field(description="Backup type for action='trigger': 'full' (entire org) or 'manual' (specific objects)."),
    ] = "",
    object_type: Annotated[
        str,
        Field(description="Object type in 'scope:key' format (e.g. 'org:wlans', 'site:devices'). Required for action='trigger' with backup_type='manual'."),
    ] = "",
    site_id: Annotated[
        str,
        Field(description="Mist site UUID for site-scoped manual backups. Used by action='trigger'."),
    ] = "",
    object_ids: Annotated[
        list[str] | None,
        Field(description="Specific Mist object UUIDs to back up. Used by action='trigger' with backup_type='manual'."),
    ] = None,
) -> str:
    """Manage Mist configuration backups: inspect versioned config snapshots, compare changes between versions, or trigger new backups.

    Each backed-up object has a version history. Use 'object_info' first to see all versions,
    then 'version_detail' or 'compare' with the version_ids from the results.
    """
    dispatchers: dict[str, Any] = {
        "object_info": _object_info,
        "version_detail": _version_detail,
        "compare": _compare,
        "trigger": _trigger,
    }

    handler = dispatchers.get(action)
    if not handler:
        return to_json({"error": f"Unknown action '{action}'. Use: {', '.join(dispatchers)}"})

    return await handler(
        ctx=ctx,
        object_id=object_id,
        version_id=version_id,
        version_id_1=version_id_1,
        version_id_2=version_id_2,
        fields=fields,
        backup_type=backup_type,
        object_type=object_type,
        site_id=site_id,
        object_ids=object_ids,
    )


async def _object_info(*, object_id: str, **_kwargs) -> str:
    """Get backup object metadata, version history, and dependencies."""
    from beanie import PydanticObjectId

    from app.modules.backup.models import BackupObject

    if not object_id:
        return to_json({"error": "object_id is required for action=object_info"})

    versions = (
        await BackupObject.find(BackupObject.object_id == object_id).sort(-BackupObject.version).to_list()
    )
    if not versions:
        return to_json({"error": f"No backup found for object_id '{object_id}'"})

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

    if not version_id:
        return to_json({"error": "version_id is required for action=version_detail"})

    try:
        obj = await BackupObject.get(PydanticObjectId(version_id))
    except Exception:
        return to_json({"error": f"Invalid version_id '{version_id}'"})

    if not obj:
        return to_json({"error": f"Version '{version_id}' not found"})

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

    if not version_id_1 or not version_id_2:
        return to_json({"error": "version_id_1 and version_id_2 are required for action=compare"})

    try:
        v1 = await BackupObject.get(PydanticObjectId(version_id_1))
        v2 = await BackupObject.get(PydanticObjectId(version_id_2))
    except Exception:
        return to_json({"error": "Invalid version ID format"})

    if not v1 or not v2:
        return to_json({"error": "One or both versions not found"})

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
            return to_json({"error": "Access denied: backup role required"})
    else:
        return to_json({"error": "Access denied: user context not available"})

    if backup_type not in ("full", "manual"):
        return to_json({"error": "backup_type must be 'full' or 'manual'"})

    if backup_type == "manual" and not object_type:
        return to_json({"error": "object_type is required for manual backups (e.g., 'org:wlans')"})

    config = await SystemConfig.get_config()
    if not config or not config.mist_org_id:
        return to_json({"error": "Mist Organization ID not configured"})

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

    return to_json(
        {"backup_type": backup_type, "status": "started", "message": "Backup started in background."}
    )

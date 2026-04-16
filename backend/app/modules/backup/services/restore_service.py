"""
Restore service for restoring Mist configurations from backups.
"""

from datetime import datetime, timezone
from typing import Any, Optional
import structlog
from beanie import PydanticObjectId

from app.modules.backup.models import BackupObject, BackupEventType
from app.services.mist_service import MistService
from app.core.exceptions import RestoreError, NotFoundError, ValidationError

logger = structlog.get_logger(__name__)

# Singleton object types — API path differs from stored object_type key.
# These use singular endpoints with no object_id in the URL.
_SINGLETON_ENDPOINTS: dict[str, dict[str, str]] = {
    "settings": {
        "site": "/api/v1/sites/{site_id}/setting",
        "org": "/api/v1/orgs/{org_id}/setting",
    },
    "info": {
        "site": "/api/v1/sites/{site_id}",
    },
    "data": {
        "org": "/api/v1/orgs/{org_id}",
    },
}

# Site-scoped singleton types: exist automatically when a site is created,
# so cascade restore must use PUT (not POST) to update them on the new site.
_SITE_SINGLETON_TYPES: set[str] = {"settings"}

# Types whose stored ``object_id`` is a shared literal key (e.g. "settings")
# because the Mist API response has no ``id`` field.  Queries against these
# types must include the composite scope (object_type, org_id, site_id) to
# avoid mutating records belonging to unrelated sites or the org.
_SINGLETON_OBJECT_TYPES: set[str] = set(_SINGLETON_ENDPOINTS.keys())


def _version_scope_query(
    object_type: str,
    object_id: str,
    org_id: Optional[str],
    site_id: Optional[str],
) -> dict[str, Any]:
    """Build a MongoDB query filter scoping to a single logical object.

    For singleton types (shared ``object_id``), returns a composite filter by
    object_type + object_id + org_id + site_id.  For non-singletons (UUID
    object_id), returns a single-key filter; the UUID is already globally
    unique.
    """
    if object_type in _SINGLETON_OBJECT_TYPES:
        return {
            "object_type": object_type,
            "object_id": object_id,
            "org_id": org_id,
            "site_id": site_id,
        }
    return {"object_id": object_id}


def _latest_deleted_by_scope_pipeline(match: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregation: find the latest version per composite scope matching ``match``,
    then keep only those whose latest version is a deletion record."""
    return [
        {"$match": match},
        {"$sort": {"version": -1}},
        {
            "$group": {
                "_id": {
                    "object_type": "$object_type",
                    "object_id": "$object_id",
                    "org_id": "$org_id",
                    "site_id": "$site_id",
                },
                "doc": {"$first": "$$ROOT"},
            }
        },
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$match": {"is_deleted": True}},
    ]


# ── Helpers for nested config field access ────────────────────────────────────


def _get_config_field(config: dict, field_path: str) -> Any:
    """Get a value at a dot-notation path, returning None if missing."""
    parts = field_path.split(".")
    current = config
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _set_config_field(config: dict, field_path: str, value: Any) -> None:
    """Set a value at a dot-notation path, creating intermediate dicts."""
    parts = field_path.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _remove_config_field(config: dict, field_path: str) -> None:
    """Remove/nullify a field at a dot-notation path."""
    parts = field_path.split(".")
    current = config
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]


class RestoreService:
    """Service for restoring configurations from backups."""

    def __init__(self, mist_service: MistService):
        self.mist_service = mist_service

    async def restore_object(
        self,
        backup_id: PydanticObjectId,
        dry_run: bool = False,
        restored_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """Restore an object from a backup."""
        backup = await BackupObject.get(backup_id)
        if not backup:
            raise NotFoundError(f"Backup {backup_id} not found")

        logger.info(
            "restore_initiated",
            backup_id=str(backup_id),
            object_type=backup.object_type,
            object_id=backup.object_id,
            version=backup.version,
            dry_run=dry_run,
            restored_by=restored_by,
        )

        try:
            validation_result = await self._validate_restore(backup)
            if not validation_result["valid"]:
                raise ValidationError(f"Restore validation failed: {validation_result['reason']}")

            if dry_run:
                return {
                    "status": "preview",
                    "backup_id": str(backup_id),
                    "object_type": backup.object_type,
                    "object_id": backup.object_id,
                    "object_name": backup.object_name,
                    "version": backup.version,
                    "configuration": backup.configuration,
                    "warnings": validation_result.get("warnings", []),
                    "deleted_dependencies": validation_result.get("deleted_dependencies", []),
                    "deleted_children": validation_result.get("deleted_children", []),
                    "active_children": validation_result.get("active_children", []),
                }

            id_remap: dict[str, str] = {}

            if validation_result.get("exists_in_mist", True):
                result = await self._restore_to_mist(backup)
                await self._create_restore_backup(backup, restored_by)
            else:
                restored_config = await self._prepare_deleted_object_config(backup)
                result = await self._create_object_in_mist(
                    backup.object_type,
                    restored_config,
                    site_id=backup.site_id,
                )
                new_object_id = result.get("id")
                if new_object_id:
                    id_remap[backup.object_id] = new_object_id
                    await self._migrate_versions_to_new_id(
                        old_object_id=backup.object_id,
                        new_object_id=new_object_id,
                        backup=backup,
                        result=result,
                        restored_by=restored_by,
                    )
                else:
                    await self._create_restore_backup(backup, restored_by)

            logger.info(
                "restore_completed",
                backup_id=str(backup_id),
                object_id=result.get("id", backup.object_id),
                restored_by=restored_by,
            )

            return {
                "status": "success",
                "backup_id": str(backup_id),
                "object_type": backup.object_type,
                "object_id": result.get("id", backup.object_id),
                "object_name": backup.object_name,
                "version": backup.version,
                "result": result,
                "id_remap": id_remap,
                "note": "Object restored with new UUID" if result.get("id") != backup.object_id else None,
            }

        except (ValidationError, NotFoundError, RestoreError):
            raise
        except Exception as e:
            logger.error(
                "restore_failed",
                backup_id=str(backup_id),
                object_id=backup.object_id,
                error=str(e),
            )
            raise RestoreError(f"Restore failed") from e

    async def restore_deleted_object(
        self,
        object_id: str,
        version: Optional[int] = None,
        dry_run: bool = False,
        restored_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """Restore a deleted object."""
        if version:
            backup = await BackupObject.find_one(
                BackupObject.object_id == object_id,
                BackupObject.version == version,
            )
            # If the requested version is a deletion record, follow the chain
            # to the actual configuration it was derived from
            if backup and backup.is_deleted and backup.previous_version_id:
                backup = await BackupObject.get(backup.previous_version_id)
        else:
            deleted_backup = (
                await BackupObject.find(
                    BackupObject.object_id == object_id,
                    BackupObject.is_deleted == True,
                )
                .sort([("version", -1)])
                .first_or_none()
            )

            if not deleted_backup:
                raise ValidationError(f"Object {object_id} is not deleted")

            if deleted_backup.previous_version_id:
                backup = await BackupObject.get(deleted_backup.previous_version_id)
            else:
                raise NotFoundError(f"No previous version found for deleted object {object_id}")

        if not backup:
            raise NotFoundError(f"Backup version not found for object {object_id}")

        logger.info(
            "restore_deleted_object",
            object_id=object_id,
            version=backup.version,
            dry_run=dry_run,
        )

        if dry_run:
            validation_result = await self._validate_restore(backup)
            return {
                "status": "preview",
                "object_id": object_id,
                "object_type": backup.object_type,
                "object_name": backup.object_name,
                "version": backup.version,
                "note": "Object will be created with a new UUID",
                "warnings": validation_result.get("warnings", []),
                "deleted_dependencies": validation_result.get("deleted_dependencies", []),
                "deleted_children": validation_result.get("deleted_children", []),
                "active_children": validation_result.get("active_children", []),
            }

        restored_config = await self._prepare_deleted_object_config(backup)

        result = await self._create_object_in_mist(
            backup.object_type,
            restored_config,
            site_id=backup.site_id,
        )

        new_object_id = result.get("id")
        if new_object_id:
            await self._migrate_versions_to_new_id(
                old_object_id=object_id,
                new_object_id=new_object_id,
                backup=backup,
                result=result,
                restored_by=restored_by,
            )
        else:
            await self._create_restore_backup(backup, restored_by)

        return {
            "status": "success",
            "original_object_id": object_id,
            "new_object_id": new_object_id or object_id,
            "object_type": backup.object_type,
            "object_name": backup.object_name,
            "note": "Object restored with new UUID",
        }

    async def cascade_restore(
        self,
        version_id: PydanticObjectId,
        include_parents: bool = True,
        include_children: bool = True,
        dry_run: bool = False,
        restored_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """Restore an object along with its deleted parents and children.

        Parents are restored first (so children can reference their new IDs),
        then the target, then children.
        """
        backup = await BackupObject.get(version_id)
        if not backup:
            raise NotFoundError(f"Backup version {version_id} not found")

        # If the backup is the deletion record, find the last active version
        if backup.is_deleted and backup.previous_version_id:
            active_backup = await BackupObject.get(backup.previous_version_id)
            if active_backup:
                backup = active_backup

        validation = await self._validate_restore(backup)

        # Build ordered restore plan
        plan: list[dict[str, Any]] = []
        id_remap: dict[str, str] = {}

        # Collect parents
        parent_backups: list[BackupObject] = []
        seen_parent_ids: set[str] = set()
        if include_parents:
            for dep in validation.get("deleted_dependencies", []):
                if dep["object_id"] in seen_parent_ids:
                    continue
                seen_parent_ids.add(dep["object_id"])
                parent_ver = await self._get_last_active_version(
                    dep["object_id"],
                    object_type=dep.get("object_type"),
                    org_id=dep.get("org_id"),
                    site_id=dep.get("site_id"),
                )
                if parent_ver:
                    parent_backups.append(parent_ver)

        # Sort parents: sites first (no site_id), then org-scoped, then site-scoped.
        # This ensures a deleted parent site is recreated before any objects that
        # live on it (e.g. wxtags), so id_remap contains the new site UUID when
        # those objects are posted.
        def _parent_sort_key(p: BackupObject) -> tuple[int, str]:
            if p.object_type == "sites":
                return (0, p.object_id)
            if p.site_id is None:
                return (1, p.object_id)
            return (2, p.object_id)

        parent_backups.sort(key=_parent_sort_key)

        # Emit plan entries in sorted order
        for pb in parent_backups:
            plan.append(
                {
                    "role": "parent",
                    "object_id": pb.object_id,
                    "object_type": pb.object_type,
                    "object_name": pb.object_name,
                    "field_path": None,
                }
            )

        # Target
        plan.append(
            {
                "role": "target",
                "object_id": backup.object_id,
                "object_type": backup.object_type,
                "object_name": backup.object_name,
            }
        )

        # Collect children
        child_backups: list[BackupObject] = []
        if include_children:
            for child_info in validation.get("deleted_children", []):
                child_ver = await self._get_last_active_version(
                    child_info["object_id"],
                    object_type=child_info.get("object_type"),
                    org_id=child_info.get("org_id"),
                    site_id=child_info.get("site_id"),
                )
                if child_ver:
                    child_backups.append(child_ver)
                    plan.append(
                        {
                            "role": "child",
                            "object_id": child_info["object_id"],
                            "object_type": child_info["object_type"],
                            "object_name": child_info.get("object_name"),
                            "field_path": child_info["field_path"],
                        }
                    )

        # Collect active children that need their reference updated
        active_child_infos: list[dict[str, Any]] = []
        if include_children:
            for child_info in validation.get("active_children", []):
                active_child_infos.append(child_info)
                plan.append(
                    {
                        "role": "update",
                        "object_id": child_info["object_id"],
                        "object_type": child_info["object_type"],
                        "object_name": child_info.get("object_name"),
                        "field_path": child_info["field_path"],
                    }
                )

        if dry_run:
            return {
                "status": "preview",
                "plan": plan,
                "warnings": validation.get("warnings", []),
                "deleted_dependencies": validation.get("deleted_dependencies", []),
                "deleted_children": validation.get("deleted_children", []),
                "active_children": validation.get("active_children", []),
            }

        restored_objects: list[dict[str, Any]] = []

        # 1. Restore parents
        for parent_backup in parent_backups:
            # Apply id_remap to site_id in case a parent site was already restored
            # earlier in this same loop (e.g. a site-scoped wxtag whose parent site
            # was also deleted and restored just before).
            effective_parent_site_id = (
                id_remap.get(parent_backup.site_id, parent_backup.site_id)
                if parent_backup.site_id
                else None
            )
            new_parent_site_id = (
                effective_parent_site_id
                if effective_parent_site_id != parent_backup.site_id
                else None
            )
            parent_config = await self._prepare_deleted_object_config(parent_backup, id_remap=id_remap)
            result = await self._create_object_in_mist(
                parent_backup.object_type,
                parent_config,
                site_id=effective_parent_site_id,
            )
            new_id = result.get("id")
            if new_id:
                id_remap[parent_backup.object_id] = new_id
                await self._migrate_versions_to_new_id(
                    old_object_id=parent_backup.object_id,
                    new_object_id=new_id,
                    backup=parent_backup,
                    result=result,
                    restored_by=restored_by,
                    id_remap=id_remap,
                    new_site_id=new_parent_site_id,
                )
            restored_objects.append(
                {
                    "role": "parent",
                    "original_object_id": parent_backup.object_id,
                    "new_object_id": new_id,
                    "object_type": parent_backup.object_type,
                    "object_name": parent_backup.object_name,
                }
            )

        # 2. Restore target (apply site_id remap if parent site was just recreated)
        target_config = await self._prepare_deleted_object_config(backup, id_remap=id_remap)
        effective_target_site_id = id_remap.get(backup.site_id, backup.site_id) if backup.site_id else None
        new_target_site_id = effective_target_site_id if effective_target_site_id != backup.site_id else None

        if backup.object_type in _SITE_SINGLETON_TYPES and effective_target_site_id:
            # Singleton target: the site singleton already exists on the (possibly
            # recreated) parent site.  Restore via PUT rather than POST.
            endpoint = self._build_endpoint(
                backup.object_type, backup.object_id, effective_target_site_id, backup.org_id
            )
            target_result = await self.mist_service.api_put(endpoint, target_config)
            await self._migrate_versions_to_new_id(
                old_object_id=backup.object_id,
                new_object_id=backup.object_id,
                backup=backup,
                result=target_result,
                restored_by=restored_by,
                id_remap=id_remap,
                new_site_id=new_target_site_id,
            )
            target_new_id = backup.object_id
        else:
            target_result = await self._create_object_in_mist(
                backup.object_type,
                target_config,
                site_id=effective_target_site_id,
            )
            target_new_id = target_result.get("id")
            if target_new_id:
                id_remap[backup.object_id] = target_new_id
                await self._migrate_versions_to_new_id(
                    old_object_id=backup.object_id,
                    new_object_id=target_new_id,
                    backup=backup,
                    result=target_result,
                    restored_by=restored_by,
                    id_remap=id_remap,
                    new_site_id=new_target_site_id,
                )

        restored_objects.append(
            {
                "role": "target",
                "original_object_id": backup.object_id,
                "new_object_id": target_new_id,
                "object_type": backup.object_type,
                "object_name": backup.object_name,
            }
        )

        # 3. Restore children
        for child_backup in child_backups:
            # Remap site_id if the parent site was just recreated with a new UUID
            effective_child_site_id = (
                id_remap.get(child_backup.site_id, child_backup.site_id) if child_backup.site_id else None
            )
            new_child_site_id = effective_child_site_id if effective_child_site_id != child_backup.site_id else None
            child_config = await self._prepare_deleted_object_config(
                child_backup,
                id_remap=id_remap,
            )

            # Singleton site objects (e.g. "settings") already exist on the newly
            # created site — restore them via PUT instead of POST.
            if child_backup.object_type in _SITE_SINGLETON_TYPES and effective_child_site_id:
                endpoint = self._build_endpoint(
                    child_backup.object_type,
                    child_backup.object_id,
                    effective_child_site_id,
                    child_backup.org_id,
                )
                child_result = await self.mist_service.api_put(endpoint, child_config)
                # Singletons keep their logical identity.  Migrate existing
                # versions to the new site_id (if remapped) and append a
                # RESTORED record that stores the PUT response.
                await self._migrate_versions_to_new_id(
                    old_object_id=child_backup.object_id,
                    new_object_id=child_backup.object_id,
                    backup=child_backup,
                    result=child_result,
                    restored_by=restored_by,
                    id_remap=id_remap,
                    new_site_id=new_child_site_id,
                )
                restored_objects.append(
                    {
                        "role": "child",
                        "original_object_id": child_backup.object_id,
                        "new_object_id": child_backup.object_id,
                        "object_type": child_backup.object_type,
                        "object_name": child_backup.object_name,
                    }
                )
            else:
                child_result = await self._create_object_in_mist(
                    child_backup.object_type,
                    child_config,
                    site_id=effective_child_site_id,
                )
                child_new_id = child_result.get("id")
                if child_new_id:
                    id_remap[child_backup.object_id] = child_new_id
                    await self._migrate_versions_to_new_id(
                        old_object_id=child_backup.object_id,
                        new_object_id=child_new_id,
                        backup=child_backup,
                        result=child_result,
                        restored_by=restored_by,
                        id_remap=id_remap,
                        new_site_id=new_child_site_id,
                    )
                restored_objects.append(
                    {
                        "role": "child",
                        "original_object_id": child_backup.object_id,
                        "new_object_id": child_new_id,
                        "object_type": child_backup.object_type,
                        "object_name": child_backup.object_name,
                    }
                )

        # 4. Update active children — patch their reference to the new parent ID
        for child_info in active_child_infos:
            try:
                await self._update_active_child_in_mist(
                    child_info,
                    id_remap,
                    backup,
                    restored_by,
                    restored_objects,
                )
            except Exception as exc:
                logger.error(
                    "active_child_update_failed",
                    child_object_id=child_info["object_id"],
                    error=str(exc),
                )

        logger.info(
            "cascade_restore_completed",
            target_id=backup.object_id,
            restored_count=len(restored_objects),
            id_remap=id_remap,
        )

        return {
            "status": "success",
            "restored_objects": restored_objects,
            "id_remap": id_remap,
        }

    async def compare_versions(
        self,
        backup_id_1: PydanticObjectId,
        backup_id_2: PydanticObjectId,
    ) -> dict[str, Any]:
        """Compare two backup versions."""
        backup1 = await BackupObject.get(backup_id_1)
        backup2 = await BackupObject.get(backup_id_2)

        if not backup1 or not backup2:
            raise NotFoundError("One or both backups not found")

        if backup1.object_id != backup2.object_id:
            raise ValidationError("Backups must be for the same object")

        differences = self._find_differences(
            backup1.configuration,
            backup2.configuration,
        )

        return {
            "object_id": backup1.object_id,
            "object_name": backup1.object_name,
            "object_type": backup1.object_type,
            "version_1": {
                "version": backup1.version,
                "backed_up_at": backup1.backed_up_at.isoformat(),
                "event_type": backup1.event_type,
            },
            "version_2": {
                "version": backup2.version,
                "backed_up_at": backup2.backed_up_at.isoformat(),
                "event_type": backup2.event_type,
            },
            "differences": differences,
            "total_differences": len(differences),
        }

    async def get_restore_preview(
        self,
        backup_id: PydanticObjectId,
    ) -> dict[str, Any]:
        """Get a preview of what would be restored."""
        backup = await BackupObject.get(backup_id)
        if not backup:
            raise NotFoundError(f"Backup {backup_id} not found")

        try:
            current_config = await self._fetch_current_config(
                backup.object_type,
                backup.object_id,
                backup.site_id,
            )
            has_current = True
        except Exception:
            current_config = None
            has_current = False

        differences = []
        if has_current:
            differences = self._find_differences(current_config, backup.configuration)

        return {
            "backup_id": str(backup_id),
            "object_id": backup.object_id,
            "object_name": backup.object_name,
            "object_type": backup.object_type,
            "version": backup.version,
            "backed_up_at": backup.backed_up_at.isoformat(),
            "has_current_version": has_current,
            "differences_from_current": differences if has_current else None,
            "total_differences": len(differences) if has_current else None,
            "backup_configuration": backup.configuration,
        }

    # ===== Internal Methods =====

    async def _validate_restore(self, backup: BackupObject) -> dict[str, Any]:
        """Validate that restore is possible.

        Returns valid flag, warnings, plus lists of deleted_dependencies
        and deleted_children for cascade restore awareness.
        """
        warnings = []

        # Check if object still exists in Mist
        try:
            await self._fetch_current_config(
                backup.object_type,
                backup.object_id,
                backup.site_id,
            )
            exists = True
        except Exception:
            exists = False
            warnings.append("Object no longer exists in Mist and would be recreated")

        # Check reference integrity + collect deleted dependencies
        from app.modules.backup.reference_map import extract_references

        refs = extract_references(backup.object_type, backup.configuration)
        deleted_dependencies: list[dict[str, Any]] = []
        seen_dep_ids: set[str] = set()

        for ref in refs:
            # Check the LATEST version to determine if the referenced object
            # is active or deleted.  Old versions always have is_deleted=False
            # even after a deletion record is added, so we must look at the
            # most recent version.
            ref_latest = (
                await BackupObject.find(
                    BackupObject.object_id == ref["target_id"],
                )
                .sort([("version", -1)])
                .first_or_none()
            )

            if ref_latest and not ref_latest.is_deleted:
                continue

            if ref_latest and ref_latest.is_deleted:
                if ref["target_id"] in seen_dep_ids:
                    continue
                seen_dep_ids.add(ref["target_id"])

                # Find version before deletion
                latest_version_id = None
                if ref_latest.previous_version_id:
                    latest_version_id = str(ref_latest.previous_version_id)

                deleted_dependencies.append(
                    {
                        "object_id": ref["target_id"],
                        "object_type": ref["target_type"],
                        "object_name": ref_latest.object_name,
                        "field_path": ref["field_path"],
                        "relationship": "parent",
                        "latest_version_id": latest_version_id,
                        "org_id": ref_latest.org_id,
                        "site_id": ref_latest.site_id,
                    }
                )
                warnings.append(
                    f"Referenced {ref['target_type']} ({ref['target_id']}) "
                    f"via '{ref['field_path']}' is deleted — cascade restore available"
                )
            else:
                warnings.append(
                    f"Referenced {ref['target_type']} ({ref['target_id']}) "
                    f"via '{ref['field_path']}' not found in backups"
                )

        # If this object is site-scoped, check whether its parent site is deleted
        if backup.site_id and backup.site_id not in seen_dep_ids:
            site_latest = (
                await BackupObject.find(
                    BackupObject.object_type == "sites",
                    BackupObject.object_id == backup.site_id,
                )
                .sort([("version", -1)])
                .first_or_none()
            )
            if site_latest and site_latest.is_deleted:
                seen_dep_ids.add(backup.site_id)
                site_version_id = str(site_latest.previous_version_id) if site_latest.previous_version_id else None
                deleted_dependencies.append(
                    {
                        "object_id": backup.site_id,
                        "object_type": "sites",
                        "object_name": site_latest.object_name,
                        "field_path": "site_id",
                        "relationship": "parent",
                        "latest_version_id": site_version_id,
                        "org_id": site_latest.org_id,
                        "site_id": None,
                    }
                )
                warnings.append(f"Parent site ({backup.site_id}) is deleted — cascade restore available")

        # Collect deleted children that reference this object
        deleted_children: list[dict[str, Any]] = []
        seen_children_keys: set[tuple[str, str, Optional[str], Optional[str]]] = set()

        ref_latest_docs = await BackupObject.aggregate(
            _latest_deleted_by_scope_pipeline({"references.target_id": backup.object_id}),
            projection_model=BackupObject,
        ).to_list()

        for doc in ref_latest_docs:
            for ref in doc.references:
                if ref.target_id == backup.object_id:
                    deleted_children.append(
                        {
                            "object_id": doc.object_id,
                            "object_type": doc.object_type,
                            "object_name": doc.object_name,
                            "field_path": ref.field_path,
                            "relationship": "child",
                            "latest_version_id": (
                                str(doc.previous_version_id) if doc.previous_version_id else None
                            ),
                            "org_id": doc.org_id,
                            "site_id": doc.site_id,
                        }
                    )
                    seen_children_keys.add(
                        (doc.object_type, doc.object_id, doc.org_id, doc.site_id)
                    )
                    break

        # If restoring a site, also collect deleted objects scoped to it (via site_id).
        # These are not captured by the references index because site membership is
        # implicit (stored as site_id on the document, not as a config-level reference).
        # Exclude "info" — it is the site-level view of the same object already being restored.
        if backup.object_type == "sites":
            site_latest_docs = await BackupObject.aggregate(
                _latest_deleted_by_scope_pipeline(
                    {"site_id": backup.object_id, "object_type": {"$ne": "info"}}
                ),
                projection_model=BackupObject,
            ).to_list()

            for doc in site_latest_docs:
                key = (doc.object_type, doc.object_id, doc.org_id, doc.site_id)
                if key in seen_children_keys:
                    continue
                seen_children_keys.add(key)

                deleted_children.append(
                    {
                        "object_id": doc.object_id,
                        "object_type": doc.object_type,
                        "object_name": doc.object_name,
                        "field_path": "site_id",
                        "relationship": "child",
                        "latest_version_id": (
                            str(doc.previous_version_id) if doc.previous_version_id else None
                        ),
                        "org_id": doc.org_id,
                        "site_id": doc.site_id,
                    }
                )

        # Collect active children that reference this object (only when target
        # will be recreated with a new UUID — active children still point to
        # the old ID and need updating).
        active_children: list[dict[str, Any]] = []
        if not exists:
            active_child_docs = (
                await BackupObject.find({"references.target_id": backup.object_id}).sort([("version", -1)]).to_list()
            )
            seen_active_keys: set[tuple[str, str, Optional[str], Optional[str]]] = set()
            for doc in active_child_docs:
                key = (doc.object_type, doc.object_id, doc.org_id, doc.site_id)
                if key in seen_active_keys or key in seen_children_keys:
                    continue
                seen_active_keys.add(key)
                if doc.is_deleted:
                    continue
                for ref in doc.references:
                    if ref.target_id == backup.object_id:
                        active_children.append(
                            {
                                "object_id": doc.object_id,
                                "object_type": doc.object_type,
                                "object_name": doc.object_name,
                                "field_path": ref.field_path,
                                "relationship": "active_child",
                                "site_id": doc.site_id,
                            }
                        )
                        break

        return {
            "valid": True,
            "exists_in_mist": exists,
            "warnings": warnings,
            "deleted_dependencies": deleted_dependencies,
            "deleted_children": deleted_children,
            "active_children": active_children,
        }

    async def _get_last_active_version(
        self,
        object_id: str,
        *,
        object_type: Optional[str] = None,
        org_id: Optional[str] = None,
        site_id: Optional[str] = None,
    ) -> Optional[BackupObject]:
        """Find the last non-deleted version of an object.

        For singleton types whose ``object_id`` is a shared type key (e.g.
        ``"settings"``), callers must provide ``object_type``, ``org_id``, and
        ``site_id`` to disambiguate.  For non-singletons with UUID object_ids,
        those extra fields are optional.
        """
        query: dict[str, Any] = {"object_id": object_id, "is_deleted": True}
        if object_type:
            query["object_type"] = object_type
        if org_id is not None:
            query["org_id"] = org_id
        if site_id is not None:
            query["site_id"] = site_id

        deleted_record = await BackupObject.find(query).sort([("version", -1)]).first_or_none()

        if not deleted_record or not deleted_record.previous_version_id:
            return None

        return await BackupObject.get(deleted_record.previous_version_id)

    async def _restore_to_mist(self, backup: BackupObject) -> dict[str, Any]:
        """Restore object to Mist via API."""
        object_type = backup.object_type
        object_id = backup.object_id
        config = backup.configuration.copy()

        readonly_fields = ["id", "org_id", "site_id", "created_time", "modified_time"]
        for field in readonly_fields:
            config.pop(field, None)

        if object_type == "wlans" and backup.site_id:
            result = await self.mist_service.update_wlan(
                backup.site_id,
                object_id,
                config,
            )
        else:
            endpoint = self._build_endpoint(object_type, object_id, backup.site_id, backup.org_id)
            result = await self.mist_service.api_put(endpoint, config)

        return result

    async def _create_object_in_mist(
        self,
        object_type: str,
        config: dict[str, Any],
        site_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new object in Mist."""
        if site_id:
            endpoint = f"/api/v1/sites/{site_id}/{object_type}"
        else:
            endpoint = f"/api/v1/orgs/{self.mist_service.org_id}/{object_type}"
        result = await self.mist_service.api_post(endpoint, config)
        return result

    async def _create_restore_backup(
        self,
        original_backup: BackupObject,
        restored_by: Optional[str],
    ) -> BackupObject:
        """Create a backup record marking the restore event.

        Uses the per-scope ``latest`` for correct ``previous_version_id``
        chaining (singletons share a literal ``object_id`` across scopes)
        but the global ``next_version`` for the version counter to stay
        compatible with the unique ``(object_id, version)`` index.
        """
        scope = _version_scope_query(
            object_type=original_backup.object_type,
            object_id=original_backup.object_id,
            org_id=original_backup.org_id,
            site_id=original_backup.site_id,
        )
        latest = await BackupObject.find(scope).sort([("version", -1)]).first_or_none()

        version = await BackupObject.next_version(original_backup.object_id)

        restore_backup = BackupObject(
            object_type=original_backup.object_type,
            object_id=original_backup.object_id,
            object_name=original_backup.object_name,
            org_id=original_backup.org_id,
            site_id=original_backup.site_id,
            configuration=original_backup.configuration,
            configuration_hash=original_backup.configuration_hash,
            version=version,
            previous_version_id=latest.id if latest else None,
            event_type=BackupEventType.RESTORED,
            backed_up_by=restored_by or "system",
            references=original_backup.references,
        )
        await restore_backup.insert()

        return restore_backup

    async def _migrate_versions_to_new_id(
        self,
        old_object_id: str,
        new_object_id: str,
        backup: BackupObject,
        result: dict[str, Any],
        restored_by: Optional[str],
        id_remap: Optional[dict[str, str]] = None,
        new_site_id: Optional[str] = None,
    ) -> None:
        """Update historical versions and append a RESTORED record from the Mist response.

        Handles two cases:

        1. Deleted-and-recreated objects (``new_object_id != old_object_id``):
           all historical versions are rewritten to use ``new_object_id``; their
           stored reference metadata is remapped via ``id_remap``; when the
           parent site was also recreated, ``site_id`` is updated.

        2. Singleton PUT restores (``new_object_id == old_object_id``): only
           ``site_id`` is migrated on old versions (bulk, via ``update_many``)
           when ``new_site_id`` is provided.

        Queries are scoped by (object_type, org_id, site_id) for singleton
        types whose ``object_id`` is a shared literal key, preventing
        cross-scope data corruption.

        The appended RESTORED record stores ``result`` (the Mist API response)
        as its ``configuration`` so the snapshot reflects what Mist actually
        accepted, including any defaults or normalization.
        """
        import hashlib
        import json
        from app.modules.backup.reference_map import extract_references
        from app.modules.backup.models import ObjectReference

        object_id_changed = old_object_id != new_object_id
        pre_remap_site_id = backup.site_id  # site_id before remap

        old_scope = _version_scope_query(
            object_type=backup.object_type,
            object_id=old_object_id,
            org_id=backup.org_id,
            site_id=pre_remap_site_id,
        )

        if object_id_changed:
            # Per-document update: object_id (and optionally reference metadata
            # and site_id) must be rewritten.  Bulk update_many would still work
            # for object_id + site_id but cannot recompute nested references.
            old_versions = await BackupObject.find(old_scope).to_list()
            for old_ver in old_versions:
                old_ver.object_id = new_object_id
                if id_remap and old_ver.references:
                    for ref in old_ver.references:
                        if ref.target_id in id_remap:
                            ref.target_id = id_remap[ref.target_id]
                if new_site_id:
                    old_ver.site_id = new_site_id
                await old_ver.save()
            versions_touched = len(old_versions)
        else:
            # Singleton case: object_id stays the same.  Only migrate site_id
            # when it actually changes, and do so with a single update_many.
            if new_site_id and new_site_id != pre_remap_site_id:
                update_result = await BackupObject.find(old_scope).update_many({"$set": {"site_id": new_site_id}})
                versions_touched = getattr(update_result, "modified_count", 0) if update_result is not None else 0
            else:
                versions_touched = 0

        # Re-query latest within the TARGET scope (post-update) to chain the
        # new RESTORED record correctly.  For singletons this is the same
        # logical scope with the (possibly new) site_id; for non-singletons
        # the new UUID is unique.
        target_scope = _version_scope_query(
            object_type=backup.object_type,
            object_id=new_object_id,
            org_id=backup.org_id,
            site_id=new_site_id or pre_remap_site_id,
        )
        latest = await BackupObject.find(target_scope).sort([("version", -1)]).first_or_none()
        # Use the global next_version for the new record's version counter to
        # stay compatible with the unique (object_id, version) index.  The
        # scoped ``latest`` above is still used for ``previous_version_id``
        # so chaining remains correct within the site's own history.
        next_ver = await BackupObject.next_version(new_object_id)

        config_hash = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()

        # Extract references from the new configuration returned by Mist
        refs = [ObjectReference(**r) for r in extract_references(backup.object_type, result)]

        # Chain the new record: for non-singleton migrations we preserve the
        # explicit ``backup.id`` link to the source version; for singletons
        # we chain to the current latest in scope (which may be a deletion
        # record) to keep the per-scope version history consistent.
        previous_version_id = backup.id if object_id_changed else (latest.id if latest else None)

        restore_backup = BackupObject(
            object_type=backup.object_type,
            object_id=new_object_id,
            object_name=backup.object_name,
            org_id=backup.org_id,
            site_id=new_site_id or pre_remap_site_id,
            configuration=result,
            configuration_hash=config_hash,
            version=next_ver,
            previous_version_id=previous_version_id,
            event_type=BackupEventType.RESTORED,
            changed_fields=[],
            backed_up_by=restored_by or "system",
            restored_from_object_id=old_object_id if object_id_changed else None,
            references=refs,
        )
        await restore_backup.insert()

        logger.info(
            "versions_migrated",
            original_object_id=old_object_id,
            new_object_id=new_object_id,
            new_site_id=new_site_id,
            versions_touched=versions_touched,
            restored_by=restored_by,
        )

    async def _update_active_child_in_mist(
        self,
        child_info: dict[str, Any],
        id_remap: dict[str, str],
        parent_backup: BackupObject,
        restored_by: Optional[str],
        restored_objects: list[dict[str, Any]],
    ) -> None:
        """Fetch an active child from Mist, patch its parent reference, PUT it back, and record a backup."""
        import hashlib, json
        from app.modules.backup.reference_map import REFERENCE_MAP, extract_references
        from app.modules.backup.models import ObjectReference

        child_object_id = child_info["object_id"]
        child_object_type = child_info["object_type"]
        field_path = child_info["field_path"]
        child_site_id = child_info.get("site_id")

        # 1. Fetch current config from Mist
        current_config = await self._fetch_current_config(
            child_object_type,
            child_object_id,
            child_site_id,
        )

        # 2. Patch the reference field with the new parent ID
        descriptors = REFERENCE_MAP.get(child_object_type, [])
        is_list = False
        for desc in descriptors:
            if desc.field_path == field_path:
                is_list = desc.is_list
                break

        patched = False
        for old_id, new_id in id_remap.items():
            current_val = _get_config_field(current_config, field_path)
            if is_list and isinstance(current_val, list) and old_id in current_val:
                new_list = [new_id if v == old_id else v for v in current_val]
                _set_config_field(current_config, field_path, new_list)
                patched = True
            elif current_val == old_id:
                _set_config_field(current_config, field_path, new_id)
                patched = True

        if not patched:
            logger.info(
                "active_child_no_patch_needed",
                child_object_id=child_object_id,
                field_path=field_path,
            )
            return

        # 3. Strip read-only fields and PUT back to Mist
        put_config = current_config.copy()
        for field in ["id", "org_id", "site_id", "created_time", "modified_time"]:
            put_config.pop(field, None)

        if child_object_type == "wlans" and child_site_id:
            result = await self.mist_service.update_wlan(
                child_site_id,
                child_object_id,
                put_config,
            )
        else:
            endpoint = self._build_endpoint(child_object_type, child_object_id, child_site_id, parent_backup.org_id)
            result = await self.mist_service.api_put(endpoint, put_config)

        # 4. Create a backup record for the updated child
        latest = (
            await BackupObject.find(
                BackupObject.object_id == child_object_id,
                BackupObject.is_deleted == False,
            )
            .sort([("version", -1)])
            .first_or_none()
        )

        version = await BackupObject.next_version(child_object_id)
        config_hash = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()

        refs = [ObjectReference(**r) for r in extract_references(child_object_type, result)]
        # Remap old IDs in the extracted references
        for ref in refs:
            if ref.target_id in id_remap:
                ref.target_id = id_remap[ref.target_id]

        restore_backup = BackupObject(
            object_type=child_object_type,
            object_id=child_object_id,
            object_name=child_info.get("object_name") or (latest.object_name if latest else None),
            org_id=parent_backup.org_id,
            site_id=child_site_id,
            configuration=result,
            configuration_hash=config_hash,
            version=version,
            previous_version_id=latest.id if latest else None,
            event_type=BackupEventType.RESTORED,
            changed_fields=[field_path],
            backed_up_by=restored_by or "system",
            references=refs,
        )
        await restore_backup.insert()

        # Remap stale parent IDs in all backup versions of this child
        all_child_versions = await BackupObject.find(
            BackupObject.object_id == child_object_id,
        ).to_list()
        for ver in all_child_versions:
            if not ver.references:
                continue
            changed = False
            for ref in ver.references:
                if ref.target_id in id_remap:
                    ref.target_id = id_remap[ref.target_id]
                    changed = True
            if changed:
                await ver.save()

        restored_objects.append(
            {
                "role": "update",
                "original_object_id": child_object_id,
                "new_object_id": child_object_id,
                "object_type": child_object_type,
                "object_name": child_info.get("object_name"),
            }
        )

        logger.info(
            "active_child_updated",
            child_object_id=child_object_id,
            child_object_type=child_object_type,
            field_path=field_path,
        )

    async def _prepare_deleted_object_config(
        self,
        backup: BackupObject,
        id_remap: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Prepare configuration for restoring a deleted object.

        - Removes read-only fields
        - Remaps reference IDs if ``id_remap`` is provided
        - Strips stale references (deleted targets with no remap)

        Uses dynamic ``extract_references()`` so that references are always
        detected even when ``backup.references`` is incomplete.
        """
        from app.modules.backup.reference_map import REFERENCE_MAP, extract_references

        config = backup.configuration.copy()

        # Remove fields that Mist will regenerate
        fields_to_remove = ["id", "org_id", "site_id", "created_time", "modified_time", "portal_template_url"]
        for field in fields_to_remove:
            config.pop(field, None)

        # Build unified reference list from stored refs + dynamic extraction
        descriptors = REFERENCE_MAP.get(backup.object_type, [])
        extracted = extract_references(backup.object_type, config)

        # Also include stored references not caught by extraction
        seen_keys: set[tuple[str, str]] = {(r["target_id"], r["field_path"]) for r in extracted}
        for ref in backup.references:
            key = (ref.target_id, ref.field_path)
            if key not in seen_keys:
                seen_keys.add(key)
                extracted.append(
                    {
                        "target_type": ref.target_type,
                        "target_id": ref.target_id,
                        "field_path": ref.field_path,
                    }
                )

        for ref_info in extracted:
            # Find matching descriptor to know if it's a list field
            is_list = False
            for desc in descriptors:
                if desc.field_path == ref_info["field_path"]:
                    is_list = desc.is_list
                    break

            target_id = ref_info["target_id"]

            if id_remap and target_id in id_remap:
                # Remap to new ID
                new_id = id_remap[target_id]
                if is_list:
                    current_val = _get_config_field(config, ref_info["field_path"])
                    if isinstance(current_val, list):
                        new_list = [new_id if v == target_id else v for v in current_val]
                        _set_config_field(config, ref_info["field_path"], new_list)
                else:
                    _set_config_field(config, ref_info["field_path"], new_id)
            else:
                # Check if target is deleted by looking at its LATEST version.
                # Old versions keep is_deleted=False even after deletion, so
                # we must check the most recent version.
                target_latest = (
                    await BackupObject.find(
                        BackupObject.object_id == target_id,
                    )
                    .sort([("version", -1)])
                    .first_or_none()
                )
                if not target_latest or target_latest.is_deleted:
                    # Target is deleted/missing — strip the stale reference
                    if is_list:
                        current_val = _get_config_field(config, ref_info["field_path"])
                        if isinstance(current_val, list):
                            new_list = [v for v in current_val if v != target_id]
                            _set_config_field(config, ref_info["field_path"], new_list)
                    else:
                        _remove_config_field(config, ref_info["field_path"])

        return config

    def _build_endpoint(
        self,
        object_type: str,
        object_id: str,
        site_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> str:
        """Build the correct Mist API endpoint, handling singleton types."""
        singleton = _SINGLETON_ENDPOINTS.get(object_type)
        if singleton:
            scope = "site" if site_id else "org"
            template = singleton.get(scope)
            if template:
                return template.format(
                    site_id=site_id,
                    org_id=org_id or self.mist_service.org_id,
                )

        if site_id:
            return f"/api/v1/sites/{site_id}/{object_type}/{object_id}"
        return f"/api/v1/orgs/{org_id or self.mist_service.org_id}/{object_type}/{object_id}"

    async def _fetch_current_config(
        self,
        object_type: str,
        object_id: str,
        site_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch current configuration from Mist."""
        endpoint = self._build_endpoint(object_type, object_id, site_id)
        return await self.mist_service.api_get(endpoint)

    async def simulate_restore(
        self,
        backup: BackupObject,
        user_id: str,
        cascade: bool = False,
    ) -> dict[str, Any]:
        """Simulate a backup restore through Digital Twin without applying to Mist."""
        try:
            from app.modules.digital_twin.services import twin_service
        except ImportError as exc:
            raise ValidationError("Digital Twin module is not available for restore simulation") from exc

        validation = await self._validate_restore(backup)

        org_id = backup.org_id or self.mist_service.org_id
        readonly_fields = ["id", "org_id", "site_id", "created_time", "modified_time"]

        if validation.get("exists_in_mist", True):
            method = "PUT"
            endpoint = self._build_endpoint(backup.object_type, backup.object_id, backup.site_id, backup.org_id)
            payload = backup.configuration.copy()
            for field in readonly_fields:
                payload.pop(field, None)
        else:
            method = "POST"
            endpoint = (
                f"/api/v1/sites/{backup.site_id}/{backup.object_type}"
                if backup.site_id
                else f"/api/v1/orgs/{org_id}/{backup.object_type}"
            )
            payload = await self._prepare_deleted_object_config(backup)
            for field in readonly_fields:
                payload.pop(field, None)

        logger.info(
            "restore_simulation_started",
            object_id=backup.object_id,
            object_type=backup.object_type,
            version=backup.version,
            method=method,
            endpoint=endpoint,
            cascade_requested=cascade,
            user_id=user_id,
        )

        source_ref = f"backup:{backup.object_type}:{backup.object_id}:v{backup.version}"
        session = await twin_service.simulate(
            user_id=user_id,
            org_id=org_id,
            writes=[{"method": method, "endpoint": endpoint, "body": payload}],
            source="backup_restore",
            source_ref=source_ref,
        )

        report = session.prediction_report
        warnings = list(validation.get("warnings", []))
        if not report:
            warnings.append(
                "Digital Twin prediction report was not generated; treat this simulation as unsafe and re-run."
            )
        if cascade:
            warnings.append(
                "Cascade restore dependencies are not included in this simulation; only the target object write was simulated."
            )

        logger.info(
            "restore_simulation_completed",
            object_id=backup.object_id,
            version=backup.version,
            twin_session_id=str(session.id),
            severity=session.overall_severity,
            execution_safe=report.execution_safe if report else False,
            warnings=len(warnings),
        )

        return {
            "status": "simulated",
            "object_id": backup.object_id,
            "object_type": backup.object_type,
            "object_name": backup.object_name,
            "version": backup.version,
            "twin_session_id": str(session.id),
            "overall_severity": session.overall_severity,
            "execution_safe": report.execution_safe if report else False,
            "summary": (
                report.summary if report else "Simulation completed without a prediction report; treat as unsafe."
            ),
            "counts": {
                "total": report.total_checks if report else 0,
                "warnings": report.warnings if report else 0,
                "errors": report.errors if report else 0,
                "critical": report.critical if report else 0,
            },
            "warnings": warnings,
            "simulate_write": {
                "method": method,
                "endpoint": endpoint,
            },
        }

    def _find_differences(
        self,
        config1: dict[str, Any],
        config2: dict[str, Any],
        prefix: str = "",
    ) -> list[dict[str, Any]]:
        """Find differences between two configurations.

        Delegates to the shared ``deep_diff`` utility and adapts the output
        format to use ``old_value``/``new_value`` keys expected by callers.
        """
        from app.modules.backup.utils import deep_diff

        raw = deep_diff(config1, config2)
        differences: list[dict[str, Any]] = []
        for d in raw:
            if d["type"] == "added":
                differences.append({"path": d["path"], "type": "added", "old_value": None, "new_value": d["value"]})
            elif d["type"] == "removed":
                differences.append({"path": d["path"], "type": "removed", "old_value": d["value"], "new_value": None})
            elif d["type"] == "modified":
                differences.append(
                    {"path": d["path"], "type": "modified", "old_value": d["old"], "new_value": d["new"]}
                )
        return differences

    async def validate_with_twin(
        self,
        backup: BackupObject,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Run Digital Twin simulation on the restore payload before executing.

        Returns the twin session report dict if the twin module is available
        and finds issues (execution_safe=False). Returns None if twin is not
        installed, the check passes, or simulation fails (non-blocking).
        """
        try:
            from app.modules.digital_twin.services import twin_service
        except ImportError:
            return None

        config = backup.configuration.copy()
        readonly_fields = ["id", "org_id", "site_id", "created_time", "modified_time"]
        for field in readonly_fields:
            config.pop(field, None)

        endpoint = self._build_endpoint(
            backup.object_type,
            backup.object_id,
            backup.site_id,
            backup.org_id,
        )

        try:
            session = await twin_service.simulate(
                user_id=user_id or "system",
                org_id=backup.org_id or self.mist_service.org_id,
                writes=[{"method": "PUT", "endpoint": endpoint, "body": config}],
                source="backup_restore",
            )
            if session.prediction_report and not session.prediction_report.execution_safe:
                return {
                    "twin_session_id": str(session.id),
                    "overall_severity": session.overall_severity,
                    "summary": session.prediction_report.summary,
                    "errors": session.prediction_report.errors,
                    "critical": session.prediction_report.critical,
                    "warnings": session.prediction_report.warnings,
                    "check_results": [
                        {
                            "check_id": r.check_id,
                            "status": r.status,
                            "summary": r.summary,
                            "remediation_hint": r.remediation_hint,
                        }
                        for r in session.prediction_report.check_results
                        if r.status in ("error", "critical", "warning")
                    ],
                }
            return None
        except Exception as e:
            logger.warning("twin_restore_validation_failed", error=str(e))
            return None

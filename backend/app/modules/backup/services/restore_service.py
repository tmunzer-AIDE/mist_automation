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


class RestoreService:
    """Service for restoring configurations from backups."""

    def __init__(self, mist_service: Optional[MistService] = None):
        """
        Initialize restore service.

        Args:
            mist_service: Optional MistService instance
        """
        self.mist_service = mist_service or MistService()

    async def restore_object(
        self,
        backup_id: PydanticObjectId,
        dry_run: bool = False,
        restored_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Restore an object from a backup.

        Args:
            backup_id: Backup object ID to restore
            dry_run: If True, preview restore without actually applying
            restored_by: User who initiated the restore

        Returns:
            dict: Restore result with status and details

        Raises:
            NotFoundError: If backup not found
            RestoreError: If restore fails
        """
        # Get backup object
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
            # Validate restore is possible
            validation_result = await self._validate_restore(backup)
            if not validation_result["valid"]:
                raise ValidationError(f"Restore validation failed: {validation_result['reason']}")

            if dry_run:
                # Return preview without applying
                return {
                    "status": "preview",
                    "backup_id": str(backup_id),
                    "object_type": backup.object_type,
                    "object_id": backup.object_id,
                    "object_name": backup.object_name,
                    "version": backup.version,
                    "configuration": backup.configuration,
                    "warnings": validation_result.get("warnings", []),
                }

            # Perform actual restore — PUT if object exists, POST if it was
            # deleted in Mist (the backup record may not be marked is_deleted
            # if the deletion happened outside the backup system).
            if validation_result.get("exists_in_mist", True):
                result = await self._restore_to_mist(backup)
                await self._create_restore_backup(backup, restored_by)
            else:
                # Object no longer exists — recreate via POST (new UUID)
                restored_config = await self._prepare_deleted_object_config(backup)
                result = await self._create_object_in_mist(
                    backup.object_type, restored_config, site_id=backup.site_id,
                )
                new_object_id = result.get("id")
                if new_object_id:
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
                "note": "Object restored with new UUID" if result.get("id") != backup.object_id else None,
            }

        except Exception as e:
            logger.error(
                "restore_failed",
                backup_id=str(backup_id),
                object_id=backup.object_id,
                error=str(e),
            )
            raise RestoreError(f"Restore failed: {str(e)}")

    async def restore_deleted_object(
        self,
        object_id: str,
        version: Optional[int] = None,
        dry_run: bool = False,
        restored_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Restore a deleted object.

        Args:
            object_id: Object UUID to restore
            version: Optional specific version to restore (defaults to last version before deletion)
            dry_run: Preview only
            restored_by: User who initiated the restore

        Returns:
            dict: Restore result

        Raises:
            NotFoundError: If object not found
            ValidationError: If object not deleted
            RestoreError: If restore fails
        """
        # Find last version before deletion
        if version:
            backup = await BackupObject.find_one(
                BackupObject.object_id == object_id,
                BackupObject.version == version,
            )
        else:
            # Get the version just before deletion
            deleted_backup = await BackupObject.find(
                BackupObject.object_id == object_id,
                BackupObject.is_deleted == True,
            ).sort([("version", -1)]).first_or_none()

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

        # The object will need a new UUID since it was deleted
        # Prepare configuration with cleaned references
        restored_config = await self._prepare_deleted_object_config(backup)

        if dry_run:
            return {
                "status": "preview",
                "object_id": object_id,
                "object_type": backup.object_type,
                "object_name": backup.object_name,
                "version": backup.version,
                "configuration": restored_config,
                "note": "Object will be created with a new UUID",
            }

        # Create the object in Mist (will get new UUID)
        result = await self._create_object_in_mist(
            backup.object_type, restored_config, site_id=backup.site_id,
        )

        new_object_id = result.get("id")
        await self._migrate_versions_to_new_id(
            old_object_id=object_id,
            new_object_id=new_object_id,
            backup=backup,
            result=result,
            restored_by=restored_by,
        )

        return {
            "status": "success",
            "original_object_id": object_id,
            "new_object_id": new_object_id,
            "object_type": backup.object_type,
            "object_name": backup.object_name,
            "note": "Object restored with new UUID",
        }

    async def compare_versions(
        self,
        backup_id_1: PydanticObjectId,
        backup_id_2: PydanticObjectId,
    ) -> dict[str, Any]:
        """
        Compare two backup versions.

        Args:
            backup_id_1: First backup ID
            backup_id_2: Second backup ID

        Returns:
            dict: Comparison result with differences

        Raises:
            NotFoundError: If either backup not found
            ValidationError: If backups are for different objects
        """
        backup1 = await BackupObject.get(backup_id_1)
        backup2 = await BackupObject.get(backup_id_2)

        if not backup1 or not backup2:
            raise NotFoundError("One or both backups not found")

        if backup1.object_id != backup2.object_id:
            raise ValidationError("Backups must be for the same object")

        # Find differences
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
        """
        Get a preview of what would be restored.

        Args:
            backup_id: Backup ID

        Returns:
            dict: Preview information

        Raises:
            NotFoundError: If backup not found
        """
        backup = await BackupObject.get(backup_id)
        if not backup:
            raise NotFoundError(f"Backup {backup_id} not found")

        # Get current state from Mist
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

        # Compare with backup
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
        """
        Validate that restore is possible.

        Returns:
            dict: Validation result with valid flag and optional warnings
        """
        warnings = []

        # Check if object still exists in Mist
        try:
            current = await self._fetch_current_config(
                backup.object_type,
                backup.object_id,
                backup.site_id,
            )
            exists = True
        except Exception:
            exists = False
            warnings.append("Object no longer exists in Mist and would be recreated")

        # Check for reference integrity
        # (e.g., WLAN references to non-existent templates)
        # This would be object-type specific in real implementation
        
        return {
            "valid": True,
            "exists_in_mist": exists,
            "warnings": warnings,
        }

    async def _restore_to_mist(self, backup: BackupObject) -> dict[str, Any]:
        """Restore object to Mist via API."""
        
        object_type = backup.object_type
        object_id = backup.object_id
        config = backup.configuration.copy()

        # Remove read-only fields
        readonly_fields = ["id", "org_id", "site_id", "created_time", "modified_time"]
        for field in readonly_fields:
            config.pop(field, None)

        # Determine API endpoint and method
        if object_type == "wlans" and backup.site_id:
            # Site WLAN
            result = await self.mist_service.update_wlan(
                backup.site_id,
                object_id,
                config,
            )
        elif backup.site_id:
            # Site-level object
            endpoint = f"/api/v1/sites/{backup.site_id}/{object_type}/{object_id}"
            result = await self.mist_service.api_put(endpoint, config)
        else:
            # Org-level object
            endpoint = f"/api/v1/orgs/{backup.org_id}/{object_type}/{object_id}"
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
        """Create a backup record marking the restore event."""
        
        # Get current version number
        latest = await BackupObject.find(
            BackupObject.object_id == original_backup.object_id,
            BackupObject.is_deleted == False,
        ).sort([("version", -1)]).first_or_none()

        version = (latest.version + 1) if latest else 1

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
    ) -> None:
        """Migrate all old versions to a new object ID and create a restore record."""
        import hashlib, json

        # Move all existing versions to the new object ID
        old_versions = await BackupObject.find(
            BackupObject.object_id == old_object_id,
        ).to_list()
        for old_ver in old_versions:
            old_ver.object_id = new_object_id
            await old_ver.save()

        max_version = max((v.version for v in old_versions), default=0)

        config_hash = hashlib.sha256(
            json.dumps(result, sort_keys=True).encode()
        ).hexdigest()

        restore_backup = BackupObject(
            object_type=backup.object_type,
            object_id=new_object_id,
            object_name=backup.object_name,
            org_id=backup.org_id,
            site_id=backup.site_id,
            configuration=result,
            configuration_hash=config_hash,
            version=max_version + 1,
            previous_version_id=backup.id,
            event_type=BackupEventType.RESTORED,
            changed_fields=[],
            backed_up_by=restored_by or "system",
            restored_from_object_id=old_object_id,
        )
        await restore_backup.insert()

        logger.info(
            "versions_migrated_to_new_id",
            original_object_id=old_object_id,
            new_object_id=new_object_id,
            versions_migrated=len(old_versions),
            restored_by=restored_by,
        )

    async def _prepare_deleted_object_config(
        self,
        backup: BackupObject,
    ) -> dict[str, Any]:
        """Prepare configuration for restoring deleted object."""
        
        config = backup.configuration.copy()

        # Remove fields that Mist will regenerate
        fields_to_remove = ["id", "org_id", "site_id", "created_time", "modified_time"]
        for field in fields_to_remove:
            config.pop(field, None)

        return config

    async def _fetch_current_config(
        self,
        object_type: str,
        object_id: str,
        site_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Fetch current configuration from Mist."""
        
        if site_id:
            # Site-level object
            endpoint = f"/api/v1/sites/{site_id}/{object_type}/{object_id}"
        else:
            # Org-level object
            endpoint = f"/api/v1/orgs/{self.mist_service.org_id}/{object_type}/{object_id}"

        return await self.mist_service.api_get(endpoint)

    def _find_differences(
        self,
        config1: dict[str, Any],
        config2: dict[str, Any],
        prefix: str = "",
    ) -> list[dict[str, Any]]:
        """
        Find differences between two configurations.

        Returns:
            List of difference records
        """
        differences = []

        all_keys = set(config1.keys()) | set(config2.keys())

        for key in all_keys:
            path = f"{prefix}.{key}" if prefix else key

            # Key added in config2
            if key not in config1:
                differences.append({
                    "path": path,
                    "type": "added",
                    "old_value": None,
                    "new_value": config2[key],
                })
                continue

            # Key removed in config2
            if key not in config2:
                differences.append({
                    "path": path,
                    "type": "removed",
                    "old_value": config1[key],
                    "new_value": None,
                })
                continue

            val1 = config1[key]
            val2 = config2[key]

            # Recursively check nested dicts
            if isinstance(val1, dict) and isinstance(val2, dict):
                nested_diffs = self._find_differences(val1, val2, path)
                differences.extend(nested_diffs)
            elif val1 != val2:
                differences.append({
                    "path": path,
                    "type": "modified",
                    "old_value": val1,
                    "new_value": val2,
                })

        return differences

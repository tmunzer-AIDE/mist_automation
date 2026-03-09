"""
Backup models for configuration backup and restore.
"""

from datetime import datetime, timezone
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field

from app.models.mixins import TimestampMixin


class BackupEventType(str, Enum):
    """Backup event types."""
    FULL_BACKUP = "full_backup"
    INCREMENTAL = "incremental"
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    RESTORED = "restored"


class BackupType(str, Enum):
    """Backup operation types."""
    FULL = "full"
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    PRE_CHANGE = "pre_change"
    WEBHOOK = "webhook"


class BackupStatus(str, Enum):
    """Backup operation status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ObjectReference(BaseModel):
    """A reference from one backup object to another."""
    target_type: str = Field(..., description="Target object type key")
    target_id: str = Field(..., description="Target object UUID")
    field_path: str = Field(..., description="Dot-notation path where reference was found")


class BackupObject(Document):
    """Individual backed up configuration object."""

    # Object identification
    object_type: str = Field(..., description="Type of Mist object")
    object_id: str = Field(..., description="Mist object ID (UUID)")
    object_name: str | None = Field(default=None, description="Object name for display")

    # Parent references
    org_id: str = Field(..., description="Mist organization ID")
    site_id: str | None = Field(default=None, description="Mist site ID (if site-specific)")
    
    # Backup data
    configuration: dict = Field(..., description="Full object configuration")
    configuration_hash: str = Field(..., description="Hash of configuration for change detection")
    
    # Versioning
    version: int = Field(default=1, description="Version number of this backup")
    previous_version_id: PydanticObjectId | None = Field(default=None, description="Reference to previous version")
    
    # Event tracking
    event_type: BackupEventType = Field(..., description="Type of event that created this backup")
    changed_fields: list[str] = Field(default_factory=list, description="List of fields that changed")
    
    # Metadata
    backed_up_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_modified_at: datetime | None = Field(default=None, description="When the configuration last changed (new version created)")
    backed_up_by: str | None = Field(default="system", description="Who initiated the backup")
    
    # Deletion tracking
    is_deleted: bool = Field(default=False, description="Whether object was deleted in Mist")
    deleted_at: datetime | None = Field(default=None, description="When object was deleted")
    
    # Restore lineage
    restored_from_object_id: str | None = Field(default=None, description="Original object ID if restored from a deleted object")

    # Cross-object references
    references: list[ObjectReference] = Field(
        default_factory=list,
        description="References to other Mist objects found in configuration",
    )

    # Git integration
    git_commit_sha: str | None = Field(default=None, description="Git commit SHA if pushed to Git")

    class Settings:
        name = "backup_objects"
        indexes = [
            "object_type",
            "object_id",
            "org_id",
            "site_id",
            [("backed_up_at", -1)],
            [("object_type", 1), ("object_id", 1), ("version", -1)],  # Compound index for latest version
            "is_deleted",
            [("references.target_id", 1)],
        ]
    
    def create_new_version(
        self,
        new_configuration: dict,
        configuration_hash: str,
        event_type: BackupEventType,
        changed_fields: list[str] = None,
        references: list["ObjectReference"] | None = None,
    ) -> "BackupObject":
        """Create a new version of this backup object."""
        return BackupObject(
            object_type=self.object_type,
            object_id=self.object_id,
            object_name=new_configuration.get("name", self.object_name),
            org_id=self.org_id,
            site_id=self.site_id,
            configuration=new_configuration,
            configuration_hash=configuration_hash,
            version=self.version + 1,
            previous_version_id=self.id,
            event_type=event_type,
            changed_fields=changed_fields or [],
            references=references or [],
        )
    
    def mark_deleted(self):
        """Mark this object as deleted."""
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)
    
    class Config:
        json_schema_extra = {
            "example": {
                "object_type": "wlan",
                "object_id": "6f4bf402-45f9-2a56-6c8b-7f83d3bc98e4",
                "object_name": "Corporate WiFi",
                "org_id": "2818e386-8dec-2562-9ede-5b8a0fbbdc71",
                "version": 5,
                "event_type": "updated",
                "changed_fields": ["ssid", "security"],
                "is_deleted": False,
            }
        }


class BackupJob(Document):
    """Backup operation/job tracking."""
    
    # Job identification
    backup_type: BackupType = Field(..., description="Type of backup operation")
    org_id: str = Field(..., description="Mist organization ID")
    org_name: str | None = Field(default=None, description="Organization name")
    site_id: str | None = Field(default=None, description="Site ID if site-specific backup")
    site_name: str | None = Field(default=None, description="Site name if site-specific")
    
    # Job status
    status: BackupStatus = Field(default=BackupStatus.PENDING, description="Backup job status")
    
    # Statistics
    object_count: int = Field(default=0, description="Number of objects backed up")
    size_bytes: int = Field(default=0, description="Total size of backup in bytes")
    
    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = Field(default=None, description="When backup started")
    completed_at: datetime | None = Field(default=None, description="When backup completed")
    created_by: PydanticObjectId | None = Field(default=None, description="User who initiated backup")
    
    # Data - stores full backup data or references to BackupObjects
    data: dict | None = Field(default=None, description="Backup data for small backups")
    object_refs: list[PydanticObjectId] = Field(default_factory=list, description="References to BackupObject documents")
    
    # Webhook trigger data
    webhook_event: list[dict] | None = Field(default=None, description="Webhook event payload(s) that triggered this backup")

    # Error tracking
    error: str | None = Field(default=None, description="Error message if backup failed")
    
    class Settings:
        name = "backup_jobs"
        indexes = [
            "org_id",
            "site_id",
            "status",
            "backup_type",
            [("created_at", -1)],
            "created_by",
        ]


class BackupLogEntry(Document):
    """Log entry for backup execution."""

    backup_job_id: PydanticObjectId = Field(..., description="Reference to BackupJob")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = Field(..., description="Log level: info, warning, error")
    phase: str = Field(..., description="Backup phase: init, org_objects, site_objects, git, complete")
    message: str = Field(..., description="Log message")
    object_type: str | None = Field(default=None, description="Object type if object-level log")
    object_id: str | None = Field(default=None, description="Object ID if object-level log")
    object_name: str | None = Field(default=None, description="Object name if object-level log")
    site_id: str | None = Field(default=None, description="Site ID if site-scoped")
    details: dict | None = Field(default=None, description="Additional details (stats, error info)")

    class Settings:
        name = "backup_log_entries"
        indexes = [
            "backup_job_id",
            [("backup_job_id", 1), ("timestamp", 1)],
            "level",
        ]


class BackupSchedule(BaseModel):
    """Backup schedule configuration."""
    enabled: bool = Field(default=True, description="Whether scheduled backups are enabled")
    cron_expression: str = Field(..., description="Cron expression for backup schedule")
    timezone: str = Field(default="UTC", description="Timezone for schedule")
    include_object_types: list[str] = Field(default_factory=list, description="Object types to include (empty = all)")


class GitConfig(BaseModel):
    """Git integration configuration."""
    enabled: bool = Field(default=False, description="Whether Git integration is enabled")
    provider: str = Field(default="github", description="Git provider: github, gitlab, gitea, etc.")
    repository_url: str = Field(..., description="Git repository URL")
    branch: str = Field(default="main", description="Branch to commit to")
    author_name: str = Field(..., description="Commit author name")
    author_email: str = Field(..., description="Commit author email")
    ssh_key: str | None = Field(default=None, description="SSH private key (encrypted)")
    access_token: str | None = Field(default=None, description="Personal access token (encrypted)")


class BackupConfig(TimestampMixin, Document):
    """Backup configuration and settings."""
    
    # Organization reference
    org_id: str = Field(..., description="Mist organization ID")
    
    # General settings
    enabled: bool = Field(default=True, description="Whether backup is enabled")
    retention_days: int = Field(default=90, description="Number of days to retain backups")
    
    # Full backup configuration
    full_backup_schedule: BackupSchedule | None = Field(default=None, description="Full backup schedule")
    
    # Incremental backup (audit webhook)
    audit_webhook_enabled: bool = Field(default=True, description="Track changes via audit webhooks")
    
    # Git integration
    git_config: GitConfig | None = Field(default=None, description="Git configuration")
    
    # Last backup info
    last_full_backup: datetime | None = Field(default=None, description="Last full backup timestamp")
    last_incremental_backup: datetime | None = Field(default=None, description="Last incremental backup timestamp")
    
    # Statistics
    total_objects_backed_up: int = Field(default=0, description="Total objects backed up")
    total_backups: int = Field(default=0, description="Total backup operations")
    last_backup_duration_seconds: int | None = Field(default=None, description="Duration of last backup")
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Settings:
        name = "backup_configs"
        indexes = [
            "org_id",
        ]
    
    def update_backup_stats(self, is_full_backup: bool, objects_count: int, duration_seconds: int):
        """Update backup statistics."""
        self.total_backups += 1
        self.total_objects_backed_up += objects_count
        self.last_backup_duration_seconds = duration_seconds
        
        if is_full_backup:
            self.last_full_backup = datetime.now(timezone.utc)
        else:
            self.last_incremental_backup = datetime.now(timezone.utc)
    
    class Config:
        json_schema_extra = {
            "example": {
                "org_id": "2818e386-8dec-2562-9ede-5b8a0fbbdc71",
                "enabled": True,
                "retention_days": 90,
                "full_backup_schedule": {
                    "enabled": True,
                    "cron_expression": "0 2 * * *",
                    "timezone": "America/Los_Angeles",
                },
                "audit_webhook_enabled": True,
            }
        }

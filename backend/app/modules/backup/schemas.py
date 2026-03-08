"""
Backup schemas.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BackupJobResponse(BaseModel):
    id: str
    backup_type: str
    org_id: str
    org_name: str | None
    site_id: str | None
    site_name: str | None
    status: str
    object_count: int
    size_bytes: int
    created_at: datetime
    created_by: str | None
    data: dict | None = None
    webhook_event: list[dict] | None = None
    error: str | None = None


class BackupJobListResponse(BaseModel):
    backups: list[BackupJobResponse]
    total: int


class BackupDiffResponse(BaseModel):
    backup_id_1: str
    backup_id_2: str
    differences: list[dict]
    added_count: int
    removed_count: int
    modified_count: int


# ── Object-centric schemas ──────────────────────────────────────────────────


class BackupObjectSummary(BaseModel):
    """Summary of a backed-up object (latest version)."""
    object_id: str
    object_type: str
    object_name: str | None
    org_id: str
    site_id: str | None
    site_name: str | None = None
    scope: str  # "org" or site name
    version_count: int
    latest_version: int
    first_backed_up_at: datetime
    last_backed_up_at: datetime
    last_modified_at: datetime | None = None
    is_deleted: bool
    event_type: str


class BackupObjectListResponse(BaseModel):
    objects: list[BackupObjectSummary]
    total: int


class BackupChangeEvent(BaseModel):
    """A single change event for the timeline."""
    id: str
    object_id: str
    object_type: str
    object_name: str | None
    site_id: str | None
    site_name: str | None = None
    scope: str
    event_type: str  # full_backup, updated, deleted, restored, etc.
    version: int
    changed_fields: list[str]
    backed_up_at: datetime
    backed_up_by: str | None


class BackupChangeListResponse(BaseModel):
    changes: list[BackupChangeEvent]
    total: int


class BackupObjectVersionResponse(BaseModel):
    """A single version of a backed-up object."""
    id: str
    object_id: str
    object_type: str
    object_name: str | None
    org_id: str
    site_id: str | None
    version: int
    event_type: str
    changed_fields: list[str]
    backed_up_at: datetime
    backed_up_by: str | None
    is_deleted: bool
    configuration: dict


# ── Log schemas ──────────────────────────────────────────────────────────────

class BackupLogEntryResponse(BaseModel):
    """A single backup execution log entry."""
    id: str
    backup_job_id: str
    timestamp: datetime
    level: str
    phase: str
    message: str
    object_type: str | None = None
    object_id: str | None = None
    object_name: str | None = None
    site_id: str | None = None
    details: dict | None = None


class BackupLogListResponse(BaseModel):
    logs: list[BackupLogEntryResponse]
    total: int


# ── Stats schemas ─────────────────────────────────────────────────────────────


class DailyObjectStats(BaseModel):
    date: str
    object_count: int


class DailyJobStats(BaseModel):
    date: str
    total: int
    completed: int
    failed: int
    webhook_events: int
    avg_duration_seconds: float | None
    min_duration_seconds: float | None
    max_duration_seconds: float | None


class BackupObjectStatsResponse(BaseModel):
    days: list[DailyObjectStats]


class BackupJobStatsResponse(BaseModel):
    days: list[DailyJobStats]

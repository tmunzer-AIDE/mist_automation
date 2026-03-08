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

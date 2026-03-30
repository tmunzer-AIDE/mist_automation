"""AP Power Scheduling models."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, IndexModel

from app.models.mixins import TimestampMixin

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class ScheduleWindow(BaseModel):
    days: list[int] = Field(..., description="0=Mon … 6=Sun")
    start: str = Field(..., description="HH:MM in site local time")
    end: str = Field(..., description="HH:MM in site local time")

    @field_validator("days")
    @classmethod
    def validate_days(cls, v: list[int]) -> list[int]:
        if not v or any(d < 0 or d > 6 for d in v):
            raise ValueError("days must be 0-6 (Mon-Sun)")
        return v

    @field_validator("start", "end")
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not _TIME_RE.match(v):
            raise ValueError("time must be HH:MM")
        return v


class PowerSchedule(TimestampMixin, Document):
    site_id: str = Field(..., description="Mist site ID")
    site_name: str = Field(..., description="Human-readable site name")
    timezone: str = Field(..., description="IANA timezone, auto-fetched from Mist on create")
    windows: list[ScheduleWindow] = Field(..., description="Off-hours windows")
    off_profile_id: str = Field(..., description="Mist device profile ID with radios disabled")
    neighbor_rssi_threshold_dbm: int = Field(default=-65, description="Min RSSI to consider APs as RF neighbors")
    roam_rssi_threshold_dbm: int = Field(default=-75, description="Client RSSI below which pre-enable neighbors")
    grace_period_minutes: int = Field(default=5, description="Wait after AP empties before disabling")
    critical_ap_macs: list[str] = Field(default_factory=list, description="APs never disabled (v1; v2 uses wxtags)")
    enabled: bool = Field(default=True)
    current_status: Literal["IDLE", "OFF_HOURS"] = Field(default="IDLE", description="Persisted for startup recovery")
    last_transition_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "power_schedules"
        indexes = [
            IndexModel([("site_id", ASCENDING)], unique=True, name="site_id_unique"),
        ]


class PowerScheduleLog(Document):
    site_id: str = Field(...)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: Literal[
        "WINDOW_START",
        "WINDOW_END",
        "CATCHUP_START",
        "CATCHUP_END",
        "AP_DISABLED",
        "AP_PENDING",
        "AP_ENABLED",
        "GRACE_TIMER_START",
        "GRACE_TIMER_EXPIRED",
        "CLIENT_DETECTED",
        "CLIENT_LEFT",
        "PROFILE_CREATED",
        "ERROR",
    ] = Field(...)
    ap_mac: str | None = Field(default=None)
    details: dict = Field(default_factory=dict)

    class Settings:
        name = "power_schedule_logs"
        indexes = [
            IndexModel([("site_id", ASCENDING), ("timestamp", ASCENDING)]),
        ]

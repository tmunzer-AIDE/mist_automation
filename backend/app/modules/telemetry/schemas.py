"""Pydantic request/response schemas for telemetry query endpoints."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ── Validation constants ──────────────────────────────────────────────────

ALLOWED_MEASUREMENTS = frozenset(
    {
        "device_summary",
        "radio_stats",
        "port_stats",
        "module_stats",
        "gateway_wan",
        "gateway_health",
        "gateway_spu",
        "gateway_resources",
        "gateway_cluster",
        "gateway_dhcp",
    }
)

ALLOWED_AGGREGATIONS = frozenset({"mean", "max", "min", "sum", "count", "last"})

_MAC_RE = re.compile(r"^[a-fA-F0-9]{12}$|^[a-fA-F0-9]{2}(:[a-fA-F0-9]{2}){5}$")
_FIELD_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_WINDOW_RE = re.compile(r"^\d+[smhd]$")
_DURATION_RE = re.compile(r"^-?\d+[smhd]$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


# ── Validators (reusable) ────────────────────────────────────────────────


def _validate_mac(v: str) -> str:
    if not _MAC_RE.match(v):
        msg = "MAC must be 12 hex chars (aabbccddeeff) or colon-separated (aa:bb:cc:dd:ee:ff)"
        raise ValueError(msg)
    return v.lower().replace(":", "")


def _validate_measurement(v: str) -> str:
    if v not in ALLOWED_MEASUREMENTS:
        msg = f"measurement must be one of: {', '.join(sorted(ALLOWED_MEASUREMENTS))}"
        raise ValueError(msg)
    return v


def _validate_field_name(v: str) -> str:
    if not _FIELD_RE.match(v):
        msg = "field must be alphanumeric + underscore, max 64 chars"
        raise ValueError(msg)
    return v


def _validate_aggregation(v: str) -> str:
    if v not in ALLOWED_AGGREGATIONS:
        msg = f"agg must be one of: {', '.join(sorted(ALLOWED_AGGREGATIONS))}"
        raise ValueError(msg)
    return v


def _validate_window(v: str) -> str:
    if not _WINDOW_RE.match(v):
        msg = "window must match pattern like 5m, 1h, 30s, 1d"
        raise ValueError(msg)
    return v


def _validate_duration(v: str) -> str:
    if v == "now()":
        return v
    if not _DURATION_RE.match(v):
        msg = "duration must match pattern like -1h, -30m, -7d, or now()"
        raise ValueError(msg)
    return v


# ── Query parameter models ───────────────────────────────────────────────


class RangeQueryParams(BaseModel):
    """Query parameters for /telemetry/query/range."""

    mac: str
    measurement: str = "device_summary"
    start: str = "-1h"
    end: str = "now()"

    @field_validator("mac")
    @classmethod
    def validate_mac(cls, v: str) -> str:
        return _validate_mac(v)

    @field_validator("measurement")
    @classmethod
    def validate_measurement(cls, v: str) -> str:
        return _validate_measurement(v)

    @field_validator("start")
    @classmethod
    def validate_start(cls, v: str) -> str:
        return _validate_duration(v)

    @field_validator("end")
    @classmethod
    def validate_end(cls, v: str) -> str:
        return _validate_duration(v)


class AggregateQueryParams(BaseModel):
    """Query parameters for /telemetry/query/aggregate."""

    site_id: str
    measurement: str = "device_summary"
    field: str
    agg: str = "mean"
    window: str = "5m"
    start: str = "-1h"
    end: str = "now()"

    @field_validator("site_id")
    @classmethod
    def validate_site_id(cls, v: str) -> str:
        if not _UUID_RE.match(v):
            msg = "site_id must be a valid UUID"
            raise ValueError(msg)
        return v

    @field_validator("measurement")
    @classmethod
    def validate_measurement(cls, v: str) -> str:
        return _validate_measurement(v)

    @field_validator("field")
    @classmethod
    def validate_field(cls, v: str) -> str:
        return _validate_field_name(v)

    @field_validator("agg")
    @classmethod
    def validate_agg(cls, v: str) -> str:
        return _validate_aggregation(v)

    @field_validator("window")
    @classmethod
    def validate_window(cls, v: str) -> str:
        return _validate_window(v)

    @field_validator("start")
    @classmethod
    def validate_start(cls, v: str) -> str:
        return _validate_duration(v)

    @field_validator("end")
    @classmethod
    def validate_end(cls, v: str) -> str:
        return _validate_duration(v)


# ── Response models ──────────────────────────────────────────────────────


class TelemetryDataPoint(BaseModel):
    """A single telemetry data point returned from InfluxDB."""

    time: datetime | str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class RangeQueryResponse(BaseModel):
    """Response for /telemetry/query/range."""

    mac: str
    measurement: str
    start: str
    end: str
    points: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class AggregateQueryResponse(BaseModel):
    """Response for /telemetry/query/aggregate."""

    site_id: str
    measurement: str
    field: str
    agg: str
    window: str
    points: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class LatestStatsResponse(BaseModel):
    """Response for /telemetry/latest/{mac}."""

    mac: str
    fresh: bool
    updated_at: float | None = None
    stats: dict[str, Any] | None = None


class TelemetrySettingsResponse(BaseModel):
    """Response for GET /telemetry/settings (read-only view)."""

    telemetry_enabled: bool
    influxdb_url: str | None = None
    influxdb_token_set: bool = False
    influxdb_org: str | None = None
    influxdb_bucket: str | None = None
    telemetry_retention_days: int = 30


class TelemetrySettingsUpdate(BaseModel):
    """Request body for PUT /telemetry/settings."""

    telemetry_enabled: bool | None = None
    influxdb_url: str | None = None
    influxdb_token: str | None = None
    influxdb_org: str | None = None
    influxdb_bucket: str | None = None
    telemetry_retention_days: int | None = Field(None, ge=1, le=365)


class ReconnectResponse(BaseModel):
    """Response for POST /telemetry/reconnect."""

    reconnected: bool
    connections: int = 0
    sites: int = 0
    message: str = ""

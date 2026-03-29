"""Pydantic request/response schemas for telemetry query endpoints."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

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
        "switch_dhcp",
    }
)

ALLOWED_AGGREGATIONS = frozenset({"mean", "max", "min", "sum", "count", "last"})

_MAC_RE = re.compile(r"^[a-fA-F0-9]{12}$|^[a-fA-F0-9]{2}(:[a-fA-F0-9]{2}){5}$")
_FIELD_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_WINDOW_RE = re.compile(r"^\d+[smhd]$")
_DURATION_RE = re.compile(r"^-?\d+[smhd]$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")




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

    site_id: str | None = None
    org_id: str | None = None
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


# ── Scope summary models ──────────────────────────────────────────────────


class BandSummary(BaseModel):
    avg_util_all: float = 0.0
    avg_noise_floor: float = 0.0


class APScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    max_cpu_util: float = 0.0
    total_clients: int = 0
    bands: dict[str, BandSummary] = Field(default_factory=dict)


class SwitchScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    total_clients: int = 0
    poe_draw_total: float = 0.0
    poe_max_total: float = 0.0
    total_dhcp_leases: int = 0


class GatewayScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    wan_links_up: int = 0
    wan_links_total: int = 0
    total_dhcp_leases: int = 0


class ScopeSummaryResponse(BaseModel):
    ap: APScopeSummary | None = None
    switch: SwitchScopeSummary | None = None
    gateway: GatewayScopeSummary | None = None


class DeviceSummaryRecord(BaseModel):
    mac: str
    site_id: str
    device_type: str
    name: str
    model: str
    cpu_util: float | None = None
    num_clients: int | None = None
    last_seen: float | None = None
    fresh: bool


class ScopeDevicesResponse(BaseModel):
    total: int
    devices: list[DeviceSummaryRecord]

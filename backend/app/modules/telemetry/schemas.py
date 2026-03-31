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
        "switch_dhcp",
        "client_stats",
    }
)

ALLOWED_AGGREGATIONS = frozenset({"mean", "max", "min", "sum", "count", "last"})
ALLOWED_DEVICE_TYPES = frozenset({"ap", "switch", "gateway"})
ALLOWED_GROUP_BY = frozenset({"band", "device_type"})

_MAC_RE = re.compile(r"^[a-fA-F0-9]{12}$|^[a-fA-F0-9]{2}(:[a-fA-F0-9]{2}){5}$")
_FIELD_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
_WINDOW_RE = re.compile(r"^\d+[smhd]$")
_DURATION_RE = re.compile(r"^-?\d+[smhd]$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")



# ── Request query param models ───────────────────────────────────────────


class RangeQueryParams(BaseModel):
    """Validated query parameters for /telemetry/query/range."""

    mac: str
    measurement: str = "device_summary"
    start: str = "-1h"
    end: str = "now()"

    @field_validator("mac")
    @classmethod
    def validate_mac(cls, v: str) -> str:
        if not _MAC_RE.match(v):
            raise ValueError("Invalid MAC address format")
        return v.lower().replace(":", "")

    @field_validator("measurement")
    @classmethod
    def validate_measurement(cls, v: str) -> str:
        if v not in ALLOWED_MEASUREMENTS:
            raise ValueError(f"Invalid measurement; allowed: {', '.join(sorted(ALLOWED_MEASUREMENTS))}")
        return v

    @field_validator("start", "end")
    @classmethod
    def validate_duration(cls, v: str) -> str:
        if v == "now()":
            return v
        if not _DURATION_RE.match(v):
            raise ValueError("Invalid duration format; expected e.g. -1h, -30m, -7d")
        return v


class AggregateQueryParams(BaseModel):
    """Validated query parameters for /telemetry/query/aggregate."""

    site_id: str | None = None
    org_id: str | None = None
    measurement: str = "device_summary"
    field: str = "cpu_util"
    agg: str = "mean"
    window: str = "5m"
    start: str = "-1h"
    end: str = "now()"

    @field_validator("site_id", "org_id")
    @classmethod
    def validate_uuid(cls, v: str | None) -> str | None:
        if v is not None and not _UUID_RE.match(v):
            raise ValueError("Invalid UUID format")
        return v

    @field_validator("measurement")
    @classmethod
    def validate_measurement(cls, v: str) -> str:
        if v not in ALLOWED_MEASUREMENTS:
            raise ValueError(f"Invalid measurement; allowed: {', '.join(sorted(ALLOWED_MEASUREMENTS))}")
        return v

    @field_validator("field")
    @classmethod
    def validate_field(cls, v: str) -> str:
        if not _FIELD_RE.match(v):
            raise ValueError("Invalid field name; must be alphanumeric/underscore, start with letter or underscore")
        return v

    @field_validator("agg")
    @classmethod
    def validate_agg(cls, v: str) -> str:
        if v not in ALLOWED_AGGREGATIONS:
            raise ValueError(f"Invalid agg; allowed: {', '.join(sorted(ALLOWED_AGGREGATIONS))}")
        return v

    @field_validator("window")
    @classmethod
    def validate_window(cls, v: str) -> str:
        if not _WINDOW_RE.match(v):
            raise ValueError("Invalid window format; expected e.g. 5m, 1h, 30s")
        return v

    @field_validator("start", "end")
    @classmethod
    def validate_duration(cls, v: str) -> str:
        if v == "now()":
            return v
        if not _DURATION_RE.match(v):
            raise ValueError("Invalid duration format; expected e.g. -1h, -30m, -7d")
        return v


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
    avg_mem_usage: float = 0.0
    total_clients: int = 0
    bands: dict[str, BandSummary] = Field(default_factory=dict)


class SwitchScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    avg_mem_usage: float = 0.0
    total_clients: int = 0
    ports_up: int = 0
    ports_total: int = 0
    poe_draw_total: float = 0.0
    poe_max_total: float = 0.0
    total_dhcp_leases: int = 0


class GatewayScopeSummary(BaseModel):
    reporting_active: int = 0
    reporting_total: int = 0
    avg_cpu_util: float = 0.0
    avg_mem_usage: float = 0.0
    wan_links_up: int = 0
    wan_links_total: int = 0
    total_dhcp_leases: int = 0
    avg_spu_cpu: float = 0.0
    total_spu_sessions: int = 0


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


class SiteSummaryRecord(BaseModel):
    site_id: str
    site_name: str = ""
    device_counts: dict[str, int] = {}
    total_devices: int = 0


class ScopeSitesResponse(BaseModel):
    sites: list[SiteSummaryRecord]
    total: int = 0


# ── Client telemetry models ──────────────────────────────────────────────


class ClientStatRecord(BaseModel):
    """A single wireless client's latest stats from LatestClientCache."""

    mac: str
    site_id: str
    ap_mac: str
    ssid: str
    band: str
    auth_type: str
    hostname: str = ""
    ip: str = ""
    manufacture: str = ""
    family: str = ""
    model: str = ""
    os: str = ""
    group: str = ""
    vlan_id: str = ""
    proto: str = ""
    username: str = ""
    rssi: float | None = None
    snr: float | None = None
    channel: int | None = None
    tx_rate: float | None = None
    rx_rate: float | None = None
    tx_bps: int = 0
    rx_bps: int = 0
    tx_bytes: int = 0
    rx_bytes: int = 0
    uptime: int = 0
    idle_time: float = 0.0
    is_guest: bool = False
    dual_band: bool = False
    last_seen: float | None = None
    fresh: bool = False


class ClientSiteSummary(BaseModel):
    """Aggregate client stats for a site (from LatestClientCache)."""

    total_clients: int = 0
    avg_rssi: float = 0.0
    band_counts: dict[str, int] = Field(default_factory=dict)
    total_tx_bps: int = 0
    total_rx_bps: int = 0


class ClientListResponse(BaseModel):
    """Response for GET /telemetry/scope/clients."""

    clients: list[ClientStatRecord] = Field(default_factory=list)
    total: int = 0

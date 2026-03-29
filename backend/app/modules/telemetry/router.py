"""Telemetry module REST endpoints."""

from __future__ import annotations

import time as _time
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import require_admin, require_impact_role
from app.models.user import User
from app.modules.telemetry.schemas import (
    _DURATION_RE,
    _FIELD_RE,
    _MAC_RE,
    _UUID_RE,
    _WINDOW_RE,
    ALLOWED_AGGREGATIONS,
    ALLOWED_MEASUREMENTS,
    APScopeSummary,
    AggregateQueryResponse,
    BandSummary,
    DeviceSummaryRecord,
    GatewayScopeSummary,
    LatestStatsResponse,
    RangeQueryResponse,
    ReconnectResponse,
    ScopeDevicesResponse,
    ScopeSummaryResponse,
    SwitchScopeSummary,
    TelemetrySettingsResponse,
    TelemetrySettingsUpdate,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


def _validate_mac_path(mac: str) -> str:
    """Validate and normalize a MAC address from path parameter."""
    if not _MAC_RE.match(mac):
        raise HTTPException(status_code=400, detail="Invalid MAC address format")
    return mac.lower().replace(":", "")


# ── Status (existing, admin only) ────────────────────────────────────────


@router.get("/status")
async def get_telemetry_status(
    _current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """Return telemetry pipeline health and stats."""
    import app.modules.telemetry as telemetry_mod

    return {
        "enabled": telemetry_mod._influxdb_service is not None,
        "influxdb": telemetry_mod._influxdb_service.get_stats() if telemetry_mod._influxdb_service else None,
        "cache_size": telemetry_mod._latest_cache.size() if telemetry_mod._latest_cache else 0,
        "websocket": telemetry_mod._ws_manager.get_status() if telemetry_mod._ws_manager else None,
        "ingestion": telemetry_mod._ingestion_service.get_stats() if telemetry_mod._ingestion_service else None,
    }


# ── Latest cached stats (from memory) ───────────────────────────────────


@router.get("/latest/{mac}", response_model=LatestStatsResponse)
async def get_latest_stats(
    mac: str,
    _current_user: User = Depends(require_impact_role),
) -> LatestStatsResponse:
    """Return latest cached stats for a device from the in-memory cache.

    This is zero-latency — reads directly from the LatestValueCache,
    not from InfluxDB. Returns fresh=False if cache is stale or empty.
    """
    import app.modules.telemetry as telemetry_mod

    mac_clean = _validate_mac_path(mac)

    if not telemetry_mod._latest_cache:
        return LatestStatsResponse(mac=mac_clean, fresh=False)

    entry = telemetry_mod._latest_cache.get_fresh_entry(mac_clean, max_age_seconds=60)
    if entry is None:
        # Try stale data
        stats = telemetry_mod._latest_cache.get(mac_clean)
        if stats:
            raw_entry = telemetry_mod._latest_cache.get_entry(mac_clean)
            return LatestStatsResponse(
                mac=mac_clean,
                fresh=False,
                updated_at=raw_entry["updated_at"] if raw_entry else None,
                stats=stats,
            )
        return LatestStatsResponse(mac=mac_clean, fresh=False)

    return LatestStatsResponse(
        mac=mac_clean,
        fresh=True,
        updated_at=entry["updated_at"],
        stats=entry["stats"],
    )


# ── Scope summary (from in-memory cache) ───────────────────────────────


def _detect_device_type(payload: dict[str, Any]) -> str | None:
    """Detect device type from a raw Mist stats payload."""
    dtype = payload.get("type")
    if dtype:
        return dtype
    model = payload.get("model")
    if isinstance(model, str) and model.startswith("AP"):
        return "ap"
    return None


def _extract_cpu_util(payload: dict[str, Any]) -> float | None:
    """Extract CPU utilization from payload (100 - cpu_stat.idle)."""
    cpu_stat = payload.get("cpu_stat")
    if cpu_stat and isinstance(cpu_stat, dict):
        idle = cpu_stat.get("idle")
        if idle is not None:
            return round(100.0 - float(idle), 2)
    return None


@router.get("/scope/summary", response_model=ScopeSummaryResponse)
async def get_scope_summary(
    site_id: str | None = Query(None, description="Site UUID to filter by"),
    _current_user: User = Depends(require_impact_role),
) -> ScopeSummaryResponse:
    """Return aggregated summary per device type from the in-memory cache.

    Zero-latency — reads directly from LatestValueCache, no InfluxDB needed.
    """
    import app.modules.telemetry as telemetry_mod

    if site_id is not None and not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")

    if telemetry_mod._latest_cache is None:
        raise HTTPException(status_code=503, detail="Telemetry cache not available")

    now = _time.time()

    # Accumulators per device type
    ap_cpus: list[float] = []
    ap_clients: int = 0
    ap_total: int = 0
    ap_active: int = 0
    # band_name -> (util_all_list, noise_floor_list)
    band_data: dict[str, tuple[list[float], list[float]]] = {}

    sw_cpus: list[float] = []
    sw_clients: int = 0
    sw_total: int = 0
    sw_active: int = 0
    sw_poe_draw: float = 0.0
    sw_poe_max: float = 0.0
    sw_dhcp_leases: int = 0

    gw_cpus: list[float] = []
    gw_total: int = 0
    gw_active: int = 0
    gw_wan_up: int = 0
    gw_wan_total: int = 0
    gw_dhcp_leases: int = 0

    for _mac, entry in telemetry_mod._latest_cache._entries.items():
        payload = entry.get("stats", {})
        updated_at = entry.get("updated_at", 0)

        if site_id and payload.get("site_id") != site_id:
            continue

        dtype = _detect_device_type(payload)
        if not dtype:
            continue

        fresh = (now - updated_at) < 60
        cpu = _extract_cpu_util(payload)

        if dtype == "ap":
            ap_total += 1
            if fresh:
                ap_active += 1
            if cpu is not None:
                ap_cpus.append(cpu)
            ap_clients += int(payload.get("num_clients", 0) or 0)
            # Radio bands
            radio_stat = payload.get("radio_stat")
            if isinstance(radio_stat, dict):
                for band_name, band_info in radio_stat.items():
                    if not isinstance(band_info, dict):
                        continue
                    if band_name not in band_data:
                        band_data[band_name] = ([], [])
                    util_all = band_info.get("util_all")
                    noise_floor = band_info.get("noise_floor")
                    if util_all is not None:
                        band_data[band_name][0].append(float(util_all))
                    if noise_floor is not None:
                        band_data[band_name][1].append(float(noise_floor))

        elif dtype == "switch":
            sw_total += 1
            if fresh:
                sw_active += 1
            if cpu is not None:
                sw_cpus.append(cpu)
            # Wired clients via clients_stats.total.num_wired_clients
            clients_stats = payload.get("clients_stats")
            if isinstance(clients_stats, dict):
                total_stats = clients_stats.get("total")
                if isinstance(total_stats, dict):
                    sw_clients += int(total_stats.get("num_wired_clients", 0) or 0)
            # PoE from module_stat
            module_stat = payload.get("module_stat")
            if isinstance(module_stat, list):
                for mod in module_stat:
                    if not isinstance(mod, dict):
                        continue
                    poe = mod.get("poe")
                    if isinstance(poe, dict):
                        sw_poe_draw += float(poe.get("power_draw", 0) or 0)
                        sw_poe_max += float(poe.get("max_power", 0) or 0)
            # DHCP from dhcpd_stat
            dhcpd_stat = payload.get("dhcpd_stat")
            if isinstance(dhcpd_stat, dict):
                for _net, net_stat in dhcpd_stat.items():
                    if isinstance(net_stat, dict):
                        sw_dhcp_leases += int(net_stat.get("num_leased", 0) or 0)

        elif dtype == "gateway":
            gw_total += 1
            if fresh:
                gw_active += 1
            if cpu is not None:
                gw_cpus.append(cpu)
            # WAN links from if_stat
            if_stat = payload.get("if_stat")
            if isinstance(if_stat, dict):
                for _if_key, port_data in if_stat.items():
                    if not isinstance(port_data, dict):
                        continue
                    if port_data.get("port_usage") != "wan":
                        continue
                    gw_wan_total += 1
                    if port_data.get("up"):
                        gw_wan_up += 1
            # DHCP from dhcpd_stat
            dhcpd_stat = payload.get("dhcpd_stat")
            if isinstance(dhcpd_stat, dict):
                for _net, net_stat in dhcpd_stat.items():
                    if isinstance(net_stat, dict):
                        gw_dhcp_leases += int(net_stat.get("num_leased", 0) or 0)

    # Build response — only include device types that have data
    ap_summary: APScopeSummary | None = None
    if ap_total > 0:
        bands = {}
        for bname, (util_list, nf_list) in band_data.items():
            bands[bname] = BandSummary(
                avg_util_all=round(sum(util_list) / len(util_list), 2) if util_list else 0.0,
                avg_noise_floor=round(sum(nf_list) / len(nf_list), 2) if nf_list else 0.0,
            )
        ap_summary = APScopeSummary(
            reporting_active=ap_active,
            reporting_total=ap_total,
            avg_cpu_util=round(sum(ap_cpus) / len(ap_cpus), 2) if ap_cpus else 0.0,
            max_cpu_util=round(max(ap_cpus), 2) if ap_cpus else 0.0,
            total_clients=ap_clients,
            bands=bands,
        )

    sw_summary: SwitchScopeSummary | None = None
    if sw_total > 0:
        sw_summary = SwitchScopeSummary(
            reporting_active=sw_active,
            reporting_total=sw_total,
            avg_cpu_util=round(sum(sw_cpus) / len(sw_cpus), 2) if sw_cpus else 0.0,
            total_clients=sw_clients,
            poe_draw_total=round(sw_poe_draw, 2),
            poe_max_total=round(sw_poe_max, 2),
            total_dhcp_leases=sw_dhcp_leases,
        )

    gw_summary: GatewayScopeSummary | None = None
    if gw_total > 0:
        gw_summary = GatewayScopeSummary(
            reporting_active=gw_active,
            reporting_total=gw_total,
            avg_cpu_util=round(sum(gw_cpus) / len(gw_cpus), 2) if gw_cpus else 0.0,
            wan_links_up=gw_wan_up,
            wan_links_total=gw_wan_total,
            total_dhcp_leases=gw_dhcp_leases,
        )

    return ScopeSummaryResponse(ap=ap_summary, switch=sw_summary, gateway=gw_summary)


@router.get("/scope/devices", response_model=ScopeDevicesResponse)
async def get_scope_devices(
    site_id: str | None = Query(None, description="Site UUID to filter by"),
    _current_user: User = Depends(require_impact_role),
) -> ScopeDevicesResponse:
    """Return a flat list of all cached devices with basic metrics.

    Zero-latency — reads directly from LatestValueCache, no InfluxDB needed.
    Sorted by last_seen descending.
    """
    import app.modules.telemetry as telemetry_mod

    if site_id is not None and not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")

    if telemetry_mod._latest_cache is None:
        raise HTTPException(status_code=503, detail="Telemetry cache not available")

    now = _time.time()
    devices: list[DeviceSummaryRecord] = []

    for mac, entry in telemetry_mod._latest_cache._entries.items():
        payload = entry.get("stats", {})
        updated_at = entry.get("updated_at", 0)

        if site_id and payload.get("site_id") != site_id:
            continue

        dtype = _detect_device_type(payload) or "unknown"
        fresh = (now - updated_at) < 60
        cpu = _extract_cpu_util(payload)

        # num_clients: AP uses payload.num_clients, switch uses clients_stats
        num_clients: int | None = None
        if dtype == "ap":
            nc = payload.get("num_clients")
            num_clients = int(nc) if nc is not None else None
        elif dtype == "switch":
            clients_stats = payload.get("clients_stats")
            if isinstance(clients_stats, dict):
                total_stats = clients_stats.get("total")
                if isinstance(total_stats, dict):
                    nc = total_stats.get("num_wired_clients")
                    num_clients = int(nc) if nc is not None else None

        devices.append(
            DeviceSummaryRecord(
                mac=mac,
                site_id=payload.get("site_id", ""),
                device_type=dtype,
                name=payload.get("name", ""),
                model=payload.get("model", ""),
                cpu_util=cpu,
                num_clients=num_clients,
                last_seen=updated_at,
                fresh=fresh,
            )
        )

    # Sort by last_seen descending
    devices.sort(key=lambda d: d.last_seen or 0, reverse=True)

    return ScopeDevicesResponse(total=len(devices), devices=devices)


# ── InfluxDB range query ────────────────────────────────────────────────


@router.get("/query/range", response_model=RangeQueryResponse)
async def query_range(
    mac: str = Query(..., description="Device MAC address"),
    measurement: str = Query("device_summary", description="InfluxDB measurement name"),
    start: str = Query("-1h", description="Range start (e.g., -1h, -30m, -7d)"),
    end: str = Query("now()", description="Range end (e.g., now(), -30m)"),
    _current_user: User = Depends(require_impact_role),
) -> RangeQueryResponse:
    """Query time-range telemetry data for a device from InfluxDB."""
    import app.modules.telemetry as telemetry_mod

    # Validate inputs (defense in depth — Flux injection prevention)
    if not _MAC_RE.match(mac):
        raise HTTPException(status_code=400, detail="Invalid MAC address format")
    mac_clean = mac.lower().replace(":", "")

    if measurement not in ALLOWED_MEASUREMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid measurement. Allowed: {', '.join(sorted(ALLOWED_MEASUREMENTS))}",
        )

    if end != "now()" and not _DURATION_RE.match(end):
        raise HTTPException(status_code=400, detail="Invalid end parameter")
    if not _DURATION_RE.match(start):
        raise HTTPException(status_code=400, detail="Invalid start parameter")

    if not telemetry_mod._influxdb_service:
        raise HTTPException(status_code=503, detail="Telemetry service not available")

    points = await telemetry_mod._influxdb_service.query_range(mac_clean, measurement, start, end)
    return RangeQueryResponse(
        mac=mac_clean,
        measurement=measurement,
        start=start,
        end=end,
        points=points,
        count=len(points),
    )


# ── InfluxDB aggregate query ────────────────────────────────────────────


@router.get("/query/aggregate", response_model=AggregateQueryResponse)
async def query_aggregate(
    site_id: str | None = Query(None, description="Site UUID (mutually exclusive with org_id)"),
    org_id: str | None = Query(None, description="Org UUID for org-wide aggregation"),
    measurement: str = Query("device_summary", description="InfluxDB measurement name"),
    field: str = Query(..., description="Field to aggregate (e.g., cpu_util)"),
    agg: str = Query("mean", description="Aggregation function"),
    window: str = Query("5m", description="Aggregation window (e.g., 5m, 1h)"),
    start: str = Query("-1h", description="Range start"),
    end: str = Query("now()", description="Range end"),
    _current_user: User = Depends(require_impact_role),
) -> AggregateQueryResponse:
    """Query aggregated telemetry data across all devices at a site or org."""
    import app.modules.telemetry as telemetry_mod

    # Validate scope params (exactly one of site_id or org_id required)
    if not site_id and not org_id:
        raise HTTPException(status_code=400, detail="Provide either site_id or org_id")
    if site_id and org_id:
        raise HTTPException(status_code=400, detail="Provide either site_id or org_id, not both")
    if site_id and not _UUID_RE.match(site_id):
        raise HTTPException(status_code=400, detail="Invalid site_id format")
    if org_id and not _UUID_RE.match(org_id):
        raise HTTPException(status_code=400, detail="Invalid org_id format")

    # Validate all other inputs (defense in depth)
    if measurement not in ALLOWED_MEASUREMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid measurement. Allowed: {', '.join(sorted(ALLOWED_MEASUREMENTS))}",
        )
    if not _FIELD_RE.match(field):
        raise HTTPException(status_code=400, detail="Invalid field name")
    if agg not in ALLOWED_AGGREGATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid aggregation. Allowed: {', '.join(sorted(ALLOWED_AGGREGATIONS))}",
        )
    if not _WINDOW_RE.match(window):
        raise HTTPException(status_code=400, detail="Invalid window format")
    if not _DURATION_RE.match(start):
        raise HTTPException(status_code=400, detail="Invalid start parameter")
    if end != "now()" and not _DURATION_RE.match(end):
        raise HTTPException(status_code=400, detail="Invalid end parameter")

    if not telemetry_mod._influxdb_service:
        raise HTTPException(status_code=503, detail="Telemetry service not available")

    points = await telemetry_mod._influxdb_service.query_aggregate(
        measurement=measurement, field=field, agg=agg, window=window,
        start=start, end=end, site_id=site_id, org_id=org_id,
    )
    return AggregateQueryResponse(
        site_id=site_id,
        org_id=org_id,
        measurement=measurement,
        field=field,
        agg=agg,
        window=window,
        points=points,
        count=len(points),
    )


# ── Settings (admin only) ───────────────────────────────────────────────


@router.get("/settings", response_model=TelemetrySettingsResponse)
async def get_telemetry_settings(
    _current_user: User = Depends(require_admin),
) -> TelemetrySettingsResponse:
    """Return current telemetry settings."""
    from app.models.system import SystemConfig

    config = await SystemConfig.get_config()
    return TelemetrySettingsResponse(
        telemetry_enabled=config.telemetry_enabled,
        influxdb_url=config.influxdb_url,
        influxdb_token_set=bool(config.influxdb_token),
        influxdb_org=config.influxdb_org,
        influxdb_bucket=config.influxdb_bucket,
        telemetry_retention_days=config.telemetry_retention_days,
    )


@router.put("/settings", response_model=TelemetrySettingsResponse)
async def update_telemetry_settings(
    settings: TelemetrySettingsUpdate,
    _current_user: User = Depends(require_admin),
) -> TelemetrySettingsResponse:
    """Update telemetry settings.

    Changes take effect on next restart or reconnect. To apply immediately,
    call POST /telemetry/reconnect after updating settings.
    """
    from app.core.security import encrypt_sensitive_data
    from app.models.system import SystemConfig

    config = await SystemConfig.get_config()
    updates = settings.model_dump(exclude_unset=True)

    for field_name, value in updates.items():
        if field_name == "influxdb_token":
            if value and isinstance(value, str) and value.strip():
                setattr(config, field_name, encrypt_sensitive_data(value))
            else:
                setattr(config, field_name, None)
        else:
            setattr(config, field_name, value)

    config.update_timestamp()
    await config.save()

    return TelemetrySettingsResponse(
        telemetry_enabled=config.telemetry_enabled,
        influxdb_url=config.influxdb_url,
        influxdb_token_set=bool(config.influxdb_token),
        influxdb_org=config.influxdb_org,
        influxdb_bucket=config.influxdb_bucket,
        telemetry_retention_days=config.telemetry_retention_days,
    )


# ── Reconnect (admin only) ──────────────────────────────────────────────


@router.post("/reconnect", response_model=ReconnectResponse)
async def reconnect_websockets(
    _current_user: User = Depends(require_admin),
) -> ReconnectResponse:
    """Stop and restart the full telemetry pipeline.

    Reads current SystemConfig, tears down all services, and reinitializes.
    Works both for restarting an existing pipeline and for first-time init
    after enabling telemetry in settings (no app restart needed).
    """
    from app.modules.telemetry.services.lifecycle import start_telemetry_pipeline, stop_telemetry_pipeline

    try:
        # Full stop (safe even if nothing is running)
        await stop_telemetry_pipeline()

        # Full start from current config
        result = await start_telemetry_pipeline()

        return ReconnectResponse(
            reconnected=True,
            connections=result.get("connections", 0),
            sites=result.get("sites", 0),
            message=f"Pipeline started: {result.get('connections', 0)} connection(s) for {result.get('sites', 0)} sites",
        )
    except ValueError as e:
        logger.warning("telemetry_reconnect_validation_error", error=str(e))
        return ReconnectResponse(
            reconnected=False,
            message="Pipeline reconnection failed: invalid configuration",
        )
    except Exception as e:
        logger.error("telemetry_reconnect_failed", error=str(e))
        # Clean up on failure
        try:
            await stop_telemetry_pipeline()
        except Exception:
            pass
        return ReconnectResponse(
            reconnected=False,
            message="Pipeline reconnection failed",
        )

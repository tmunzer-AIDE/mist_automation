"""Telemetry module REST endpoints."""

from __future__ import annotations

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
    AggregateQueryResponse,
    LatestStatsResponse,
    RangeQueryResponse,
    ReconnectResponse,
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

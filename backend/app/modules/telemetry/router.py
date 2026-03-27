"""Telemetry module REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies import require_admin
from app.models.user import User

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


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

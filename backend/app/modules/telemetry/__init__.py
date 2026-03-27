"""Telemetry module — WebSocket device stats ingestion pipeline.

Module-level singletons are initialized during app startup when
telemetry_enabled is True in SystemConfig.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache

_influxdb_service: InfluxDBService | None = None
_latest_cache: LatestValueCache | None = None

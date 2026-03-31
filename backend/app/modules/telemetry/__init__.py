"""Telemetry module — WebSocket device stats ingestion pipeline.

Module-level singletons are initialized during app startup when
telemetry_enabled is True in SystemConfig.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.telemetry.services.client_ws_manager import ClientWsManager
    from app.modules.telemetry.services.cov_filter import CoVFilter
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.latest_client_cache import LatestClientCache
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache
    from app.modules.telemetry.services.mist_ws_manager import MistWsManager

_influxdb_service: InfluxDBService | None = None
_latest_cache: LatestValueCache | None = None
_client_cache: LatestClientCache | None = None
_cov_filter: CoVFilter | None = None
_ingestion_service: IngestionService | None = None
_ws_manager: MistWsManager | None = None
_client_ws_manager: ClientWsManager | None = None

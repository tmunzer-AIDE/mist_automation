"""Telemetry pipeline lifecycle management.

Extracted from main.py lifespan to allow the reconnect endpoint to
start/stop the full pipeline without restarting the app.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def start_telemetry_pipeline() -> dict:
    """Start the full telemetry pipeline from SystemConfig.

    Returns a status dict with sites count and connection info.
    Raises on failure (caller should clean up).
    """
    import mistapi

    import app.modules.telemetry as telemetry_mod
    from app.core.security import decrypt_sensitive_data
    from app.models.system import SystemConfig
    from app.modules.telemetry.services.cov_filter import CoVFilter
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache
    from app.modules.telemetry.services.mist_ws_manager import MistWsManager
    from app.services.mist_service_factory import create_mist_service

    config = await SystemConfig.get_config()

    if not config.telemetry_enabled:
        raise ValueError("Telemetry is not enabled in settings")
    if not config.influxdb_url:
        raise ValueError("InfluxDB URL is not configured")
    if not config.influxdb_token:
        raise ValueError("InfluxDB token is not configured")

    # 1. Core services
    telemetry_mod._latest_cache = LatestValueCache()
    telemetry_mod._cov_filter = CoVFilter()
    telemetry_mod._influxdb_service = InfluxDBService(
        url=config.influxdb_url,
        token=decrypt_sensitive_data(config.influxdb_token),
        org=config.influxdb_org or "mist_automation",
        bucket=config.influxdb_bucket or "mist_telemetry",
    )
    await telemetry_mod._influxdb_service.start()

    # 2. Ingestion service
    org_id = config.mist_org_id or ""
    telemetry_mod._ingestion_service = IngestionService(
        influxdb=telemetry_mod._influxdb_service,
        cache=telemetry_mod._latest_cache,
        cov_filter=telemetry_mod._cov_filter,
        org_id=org_id,
    )
    await telemetry_mod._ingestion_service.start()

    # 3. WebSocket manager — get sites from Mist
    site_ids: list[str] = []
    if org_id:
        mist = await create_mist_service()
        api_session = mist.get_session()
        resp = await mistapi.arun(
            mistapi.api.v1.orgs.sites.listOrgSites, api_session, org_id, limit=1000
        )
        site_ids = [s["id"] for s in (resp.data or [])]
        if site_ids:
            telemetry_mod._ws_manager = MistWsManager(
                api_session=api_session,
                message_queue=telemetry_mod._ingestion_service.get_queue(),
            )
            await telemetry_mod._ws_manager.start(site_ids)

    logger.info(
        "telemetry_started",
        sites=len(site_ids),
        ws_connections=telemetry_mod._ws_manager.get_status()["connections"] if telemetry_mod._ws_manager else 0,
    )

    return {
        "sites": len(site_ids),
        "connections": telemetry_mod._ws_manager.get_status()["connections"] if telemetry_mod._ws_manager else 0,
    }


async def stop_telemetry_pipeline() -> None:
    """Stop the full telemetry pipeline and clear all singletons."""
    import app.modules.telemetry as telemetry_mod

    if telemetry_mod._ws_manager:
        await telemetry_mod._ws_manager.stop()
        telemetry_mod._ws_manager = None
    if telemetry_mod._ingestion_service:
        await telemetry_mod._ingestion_service.stop()
        telemetry_mod._ingestion_service = None
    if telemetry_mod._influxdb_service:
        await telemetry_mod._influxdb_service.stop()
        telemetry_mod._influxdb_service = None
    telemetry_mod._latest_cache = None
    telemetry_mod._cov_filter = None
    logger.info("telemetry_stopped")

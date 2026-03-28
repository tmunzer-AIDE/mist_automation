"""System health aggregation and broadcasting."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from app.config import settings
from app.core.database import Database

logger = structlog.get_logger(__name__)

_BROADCAST_INTERVAL = 10  # seconds
_health_task: asyncio.Task | None = None


async def _get_redis_client():
    """Get an async Redis client."""
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _check_mongodb() -> dict[str, Any]:
    """Check MongoDB health and gather stats."""
    try:
        db = Database.get_database()
        server_info = await db.client.server_info()
        db_stats = await db.command("dbStats")
        return {
            "status": "connected",
            "collections": db_stats.get("collections", 0),
            "total_documents": db_stats.get("objects", 0),
            "storage_size_mb": round(db_stats.get("dataSize", 0) / 1024 / 1024, 1),
            "uptime_seconds": server_info.get("uptime", 0),
        }
    except Exception:
        return {"status": "disconnected", "collections": 0, "total_documents": 0, "storage_size_mb": 0.0, "uptime_seconds": 0}


async def _check_redis() -> dict[str, Any]:
    """Check Redis health and gather stats."""
    try:
        client = await _get_redis_client()
        try:
            await client.ping()
            memory = await client.info("memory")
            clients = await client.info("clients")
            server = await client.info("server")
            return {
                "status": "connected",
                "used_memory_mb": round(memory.get("used_memory", 0) / 1024 / 1024, 1),
                "connected_clients": clients.get("connected_clients", 0),
                "uptime_seconds": server.get("uptime_in_seconds", 0),
            }
        finally:
            await client.aclose()
    except Exception:
        return {"status": "disconnected", "used_memory_mb": 0.0, "connected_clients": 0, "uptime_seconds": 0}


def _check_telemetry() -> dict[str, dict[str, Any]]:
    """Gather telemetry pipeline stats from module singletons."""
    import app.modules.telemetry as telemetry_mod

    influxdb: dict[str, Any]
    if telemetry_mod._influxdb_service:
        raw = telemetry_mod._influxdb_service.get_stats()
        cap = raw.get("buffer_capacity", 1)
        influxdb = {
            "status": "connected" if raw.get("connected") else "disconnected",
            "buffer_size": raw.get("buffer_size", 0),
            "buffer_capacity": cap,
            "buffer_pct": round(raw.get("buffer_size", 0) / cap * 100, 1) if cap else 0.0,
            "points_written": raw.get("points_written", 0),
            "points_dropped": raw.get("points_dropped", 0),
            "flush_count": raw.get("flush_count", 0),
            "last_flush_at": raw.get("last_flush_at", 0),
            "last_error": raw.get("last_error"),
        }
    else:
        influxdb = {
            "status": "disconnected",
            "buffer_size": 0,
            "buffer_capacity": 0,
            "buffer_pct": 0.0,
            "points_written": 0,
            "points_dropped": 0,
            "flush_count": 0,
            "last_flush_at": 0,
            "last_error": None,
        }

    mist_ws: dict[str, Any]
    if telemetry_mod._ws_manager:
        raw = telemetry_mod._ws_manager.get_status()
        ready = raw.get("connections_ready", 0)
        total = raw.get("connections", 0)
        if total == 0:
            ws_status = "disconnected"
        elif ready < total:
            ws_status = "degraded"
        else:
            ws_status = "connected"
        mist_ws = {
            "status": ws_status,
            "connections": total,
            "connections_ready": ready,
            "sites_subscribed": raw.get("sites_subscribed", 0),
            "messages_received": raw.get("messages_received", 0),
            "messages_bridge_dropped": raw.get("messages_bridge_dropped", 0),
            "last_message_at": raw.get("last_message_at", 0),
            "started_at": raw.get("started_at", 0),
        }
    else:
        mist_ws = {
            "status": "disconnected",
            "connections": 0,
            "connections_ready": 0,
            "sites_subscribed": 0,
            "messages_received": 0,
            "messages_bridge_dropped": 0,
            "last_message_at": 0,
            "started_at": 0,
        }

    ingestion: dict[str, Any]
    if telemetry_mod._ingestion_service:
        raw = telemetry_mod._ingestion_service.get_stats()
        cap = raw.get("queue_capacity", 1)
        ingestion = {
            "status": "active" if raw.get("running") else "stopped",
            "queue_size": raw.get("queue_size", 0),
            "queue_capacity": cap,
            "queue_pct": round(raw.get("queue_size", 0) / cap * 100, 1) if cap else 0.0,
            "messages_processed": raw.get("messages_processed", 0),
            "points_extracted": raw.get("points_extracted", 0),
            "points_written": raw.get("points_written", 0),
            "points_filtered": raw.get("points_filtered", 0),
            "last_message_at": raw.get("last_message_at", 0),
        }
    else:
        ingestion = {
            "status": "stopped",
            "queue_size": 0,
            "queue_capacity": 0,
            "queue_pct": 0.0,
            "messages_processed": 0,
            "points_extracted": 0,
            "points_written": 0,
            "points_filtered": 0,
            "last_message_at": 0,
        }

    return {"influxdb": influxdb, "mist_websocket": mist_ws, "ingestion": ingestion}


def _check_workers() -> dict[str, Any]:
    """Check scheduler status."""
    try:
        from app.modules.automation.workers.scheduler import get_scheduler

        scheduler = get_scheduler()
        return {
            "status": "active" if scheduler._initialized else "stopped",
            "scheduled_jobs": len(scheduler.get_scheduled_workflows()) if scheduler._initialized else 0,
        }
    except Exception:
        return {"status": "stopped", "scheduled_jobs": 0}


def _check_app_websocket() -> dict[str, Any]:
    """Check app WebSocket manager stats."""
    from app.core.websocket import ws_manager

    return ws_manager.get_stats()


async def collect_system_health() -> dict[str, Any]:
    """Aggregate health from all infrastructure services."""
    mongo_result, redis_result = await asyncio.gather(
        _check_mongodb(),
        _check_redis(),
        return_exceptions=True,
    )

    if isinstance(mongo_result, Exception):
        mongo_result = {
            "status": "disconnected",
            "collections": 0,
            "total_documents": 0,
            "storage_size_mb": 0.0,
            "uptime_seconds": 0,
        }
    if isinstance(redis_result, Exception):
        redis_result = {"status": "disconnected", "used_memory_mb": 0.0, "connected_clients": 0, "uptime_seconds": 0}

    telemetry = _check_telemetry()
    scheduler = _check_workers()
    app_ws = _check_app_websocket()

    services = {
        "mongodb": mongo_result,
        "redis": redis_result,
        "influxdb": telemetry["influxdb"],
        "mist_websocket": telemetry["mist_websocket"],
        "ingestion": telemetry["ingestion"],
        "app_websocket": app_ws,
        "scheduler": scheduler,
    }

    statuses = [s.get("status", "") for s in services.values()]
    if any(s in ("disconnected", "stopped", "down") for s in statuses):
        overall = "down"
    elif any(s in ("degraded",) for s in statuses):
        overall = "degraded"
    else:
        overall = "operational"

    return {
        "overall_status": overall,
        "checked_at": time.time(),
        "services": services,
    }


async def _broadcast_loop() -> None:
    """Periodically broadcast system health to subscribed admin clients."""
    from app.core.websocket import ws_manager

    while True:
        try:
            await asyncio.sleep(_BROADCAST_INTERVAL)
            if not ws_manager._channels.get("system:health"):
                continue
            health = await collect_system_health()
            await ws_manager.broadcast("system:health", {"type": "health_update", "data": health})
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("system_health_broadcast_error", error=str(e))


def start_health_broadcaster() -> None:
    """Start the background health broadcaster task."""
    global _health_task
    if _health_task is None or _health_task.done():
        _health_task = asyncio.create_task(_broadcast_loop(), name="system-health-broadcaster")


async def stop_health_broadcaster() -> None:
    """Stop the background health broadcaster task."""
    global _health_task
    if _health_task and not _health_task.done():
        _health_task.cancel()
        try:
            await _health_task
        except asyncio.CancelledError:
            pass
        _health_task = None

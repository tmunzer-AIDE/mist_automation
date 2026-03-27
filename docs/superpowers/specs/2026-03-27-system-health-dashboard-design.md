# System Health Dashboard

## Overview

Add infrastructure health monitoring to the admin area. Currently the admin stats page only shows business-level metrics (workflow/execution/backup counts). Infrastructure services (MongoDB, Redis, InfluxDB, WebSocket) have no visibility.

**Single surface:** Merge infrastructure health into the existing admin stats page (`features/admin/stats/`). No new routes -- everything on one page.

## Backend

### New endpoint: `GET /admin/system-health`

Single endpoint aggregating all infrastructure health into one response. Admin-only (`require_admin`).

```python
{
    "overall_status": "operational" | "degraded" | "down",
    "checked_at": 1774642500,
    "services": {
        "mongodb": {
            "status": "connected" | "disconnected",
            "collections": 12,
            "total_documents": 45321,
            "storage_size_mb": 128.5,
            "uptime_seconds": 1209600
        },
        "redis": {
            "status": "connected" | "disconnected",
            "used_memory_mb": 24.3,
            "connected_clients": 3,
            "uptime_seconds": 1209600
        },
        "influxdb": {
            "status": "connected" | "disconnected",
            "buffer_size": 340,
            "buffer_capacity": 10000,
            "buffer_pct": 3.4,
            "points_written": 42891,
            "points_dropped": 0,
            "flush_count": 128,
            "last_flush_at": 1774642497,
            "last_error": null
        },
        "mist_websocket": {
            "status": "connected" | "disconnected" | "degraded",
            "connections": 2,
            "connections_ready": 2,
            "sites_subscribed": 14,
            "messages_received": 12470,
            "messages_bridge_dropped": 0,
            "last_message_at": 1774642499,
            "started_at": 1774641200
        },
        "ingestion": {
            "status": "running" | "stopped",
            "queue_size": 12,
            "queue_capacity": 10000,
            "queue_pct": 0.12,
            "messages_processed": 8412,
            "points_extracted": 42891,
            "points_written": 42891,
            "points_filtered": 31204,
            "last_message_at": 1774642499
        },
        "app_websocket": {
            "connected_clients": 3,
            "active_channels": 5,
            "subscriptions": 8
        },
        "scheduler": {
            "status": "running" | "stopped",
            "scheduled_jobs": 3
        }
    }
}
```

**Implementation details:**

- MongoDB health: `motor` client `server_info()` for uptime, `list_collection_names()` + `estimated_document_count()` for collection/doc stats, `command("dbStats")` for storage size
- Redis health: `redis.info("memory")` for used_memory, `redis.info("clients")` for connected_clients, `redis.info("server")` for uptime
- InfluxDB: reuse existing `InfluxDBService.get_stats()`, add `test_connection()` for status
- Mist WS: reuse existing `MistWsManager.get_status()`
- Ingestion: reuse existing `IngestionService.get_stats()`
- App WebSocket: add `get_stats()` to `WebSocketManager` in `app/core/websocket.py` -- count `_channels`, `_client_channels`
- Scheduler: reuse existing logic from `/admin/workers/status`

`overall_status` derived from worst service status: all connected = operational, any degraded = degraded, any disconnected/down = down.

### WebSocket channel: `system:health`

Push system health updates every 10 seconds to subscribed admin clients. Reuse existing `ws_manager.broadcast()` pattern. Only broadcast when at least one client is subscribed (lazy -- no overhead when no admin is watching).

Use `create_background_task()` to run a periodic health check loop that:
1. Calls the same logic as `GET /admin/system-health`
2. Broadcasts to `system:health` channel
3. Only runs while subscribers exist

## Frontend

### Merged into existing admin stats page (`features/admin/stats/`)

No new route. The existing stats page gets three new sections added ABOVE the current business stats grid. Layout top to bottom:

**Section 1: Status ribbon**
Full-width banner with overall status and last-checked timestamp.
- Green background (`--app-success-bg`): "All Systems Operational"
- Amber background (`--app-warning-bg`): "Degraded Performance"
- Red background (`--app-error-status-bg`): "Service Disruption"

**Section 2: KPI tiles**
5 stat tiles in a responsive grid (`repeat(auto-fit, minmax(140px, 1fr))`):

| Tile | Source |
|------|--------|
| Services Up (e.g., "4/4") | Count of connected services |
| msg/sec | Mist WS messages_received delta |
| Errors | influxdb.points_dropped |
| Buffer % | influxdb.buffer_pct |
| Sites | mist_websocket.sites_subscribed |

Each tile: large number (32px bold), small uppercase label (11px). Color the number red if unhealthy.

**Section 3: Service detail panels**
`mat-accordion` with `multi="true"`, panels expanded by default:

**Infrastructure** panel:
- MongoDB card: status badge, collections, total docs, storage size, uptime
- Redis card: status badge, used memory, connected clients, uptime

**Telemetry Pipeline** panel:
- InfluxDB card: status badge, buffer gauge (`mat-progress-bar`), points written/dropped, flush count, last flush time, last error
- Mist WebSocket card: status badge, connections (ready/total), sites subscribed, message rate, bridge drops, last message time
- Ingestion card: status badge, queue gauge (`mat-progress-bar`), messages processed, points extracted/written/filtered

**App WebSocket** panel:
- Single card: connected clients, active channels, total subscriptions

**Workers** panel:
- Scheduler card: status badge, scheduled job count

**Section 4: Existing business stats** (unchanged)
The current `.stats-grid` with Users, Workflows, Executions, Backups, Webhooks, Workers cards remains below the infrastructure sections.

**Card design:**
- `mat-card` with 4px left border colored by service status
- Header: service icon + name + `StatusBadgeComponent`
- Body: `.status-grid` with label/value rows (reuse from telemetry settings)
- Buffer/queue gauges: `mat-progress-bar mode="determinate"` with threshold-based color classes (green <70%, amber 70-90%, red >90%)
- Relative timestamps: "3s ago", "2m ago" computed from Unix timestamps

**Auto-refresh:**
Subscribe to `system:health` WS channel on component init. Update health signals on each message. Business stats remain fetched once on load (no change). Show "Live" indicator next to the status ribbon timestamp.

### Service

Add `getSystemHealth(): Observable<SystemHealth>` to `AdminService`.
WS subscription via existing `WebSocketService.subscribe('system:health')`.

## Styling

Use existing `--app-*` CSS custom properties:
- `--app-success` / `--app-success-bg` for healthy
- `--app-warning` / `--app-warning-bg` for degraded
- `--app-error-status` / `--app-error-status-bg` for down
- `--app-neutral` for disabled/unknown

Dark mode handled automatically via `.dark-theme` overrides on these properties.

## Files to create/modify

**Backend:**
- `backend/app/api/v1/admin.py` -- add `GET /admin/system-health` endpoint
- `backend/app/core/websocket.py` -- add `get_stats()` to `WebSocketManager`
- `backend/app/core/tasks.py` or new `backend/app/api/v1/system_health_broadcaster.py` -- periodic WS broadcast task

**Frontend:**
- `frontend/src/app/features/admin/stats/stats.component.ts` -- add health data fetching, WS subscription, health signals
- `frontend/src/app/features/admin/stats/stats.component.html` -- add ribbon, KPI tiles, service detail panels above existing grid
- `frontend/src/app/features/admin/stats/stats.component.scss` -- styles for ribbon, KPI tiles, service cards, buffer gauges
- `frontend/src/app/core/services/admin.service.ts` -- add `getSystemHealth()`
- `frontend/src/app/core/models/admin.model.ts` -- add `SystemHealth` interface

## Out of scope

- Historical health trends (would need InfluxDB self-monitoring -- future)
- Alerting on service degradation (future -- could integrate with notification_service)
- Celery worker status (Redis-based inspection is complex and fragile)
- Smee.io status (dev-only, not production-relevant)
- LLM provider health (already has its own test-connection in LLM settings)

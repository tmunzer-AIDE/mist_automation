# System Health Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add infrastructure health monitoring (MongoDB, Redis, InfluxDB, WebSocket) to the existing admin stats page with real-time updates via WebSocket.

**Architecture:** Single new backend endpoint (`GET /admin/system-health`) aggregates all infrastructure service health. A background task broadcasts updates every 10s on the `system:health` WS channel. The frontend stats component adds a status ribbon, KPI tiles, and expandable service detail panels above the existing business stats grid.

**Tech Stack:** Python/FastAPI (backend), Angular 21 + Material (frontend), Motor (MongoDB), redis-py (Redis), InfluxDB client (existing), WebSocket (existing infra)

**Spec:** `docs/superpowers/specs/2026-03-27-system-health-dashboard-design.md`

---

### File Structure

**Backend — create:**
- `backend/app/api/v1/system_health.py` — health aggregation logic + broadcaster

**Backend — modify:**
- `backend/app/api/v1/admin.py` — add `GET /admin/system-health` endpoint
- `backend/app/core/websocket.py` — add `get_stats()` to `WebSocketManager`
- `backend/app/main.py` — start/stop health broadcaster in lifespan

**Frontend — modify:**
- `frontend/src/app/core/models/admin.model.ts` — add `SystemHealth` interface
- `frontend/src/app/core/services/admin.service.ts` — add `getSystemHealth()`
- `frontend/src/app/features/admin/stats/stats.component.ts` — add health data, WS subscription
- `frontend/src/app/features/admin/stats/stats.component.html` — add ribbon, KPIs, service panels
- `frontend/src/app/features/admin/stats/stats.component.scss` — styles for new sections

---

### Task 1: Add `get_stats()` to WebSocketManager

**Files:**
- Modify: `backend/app/core/websocket.py`
- Test: `backend/tests/unit/test_websocket_stats.py` (create)

- [ ] **Step 1: Write the test**

Create `backend/tests/unit/test_websocket_stats.py`:

```python
"""Unit tests for WebSocketManager.get_stats()."""

from unittest.mock import MagicMock

from app.core.websocket import WebSocketManager


class TestWebSocketManagerStats:
    def test_empty_manager_stats(self):
        mgr = WebSocketManager()
        stats = mgr.get_stats()
        assert stats["connected_clients"] == 0
        assert stats["active_channels"] == 0
        assert stats["total_subscriptions"] == 0

    def test_stats_with_clients_and_channels(self):
        mgr = WebSocketManager()
        ws1 = MagicMock()
        ws2 = MagicMock()
        mgr._client_channels[ws1] = {"ch1", "ch2"}
        mgr._client_channels[ws2] = {"ch1"}
        mgr._channels["ch1"] = {ws1, ws2}
        mgr._channels["ch2"] = {ws1}
        mgr._last_pong[ws1] = 1.0
        mgr._last_pong[ws2] = 2.0

        stats = mgr.get_stats()
        assert stats["connected_clients"] == 2
        assert stats["active_channels"] == 2
        assert stats["total_subscriptions"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/test_websocket_stats.py -v`
Expected: FAIL — `WebSocketManager has no attribute 'get_stats'`

- [ ] **Step 3: Implement `get_stats()`**

Add to `backend/app/core/websocket.py`, inside the `WebSocketManager` class, before the `start_heartbeat` method:

```python
    def get_stats(self) -> dict[str, int]:
        """Return WebSocket connection statistics."""
        total_subs = sum(len(subs) for subs in self._channels.values())
        return {
            "connected_clients": len(self._client_channels),
            "active_channels": len(self._channels),
            "total_subscriptions": total_subs,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/test_websocket_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/websocket.py backend/tests/unit/test_websocket_stats.py
git commit -m "feat(admin): add get_stats() to WebSocketManager"
```

---

### Task 2: Create system health aggregation module

**Files:**
- Create: `backend/app/api/v1/system_health.py`
- Test: `backend/tests/unit/test_system_health.py` (create)

- [ ] **Step 1: Write test for health aggregation**

Create `backend/tests/unit/test_system_health.py`:

```python
"""Unit tests for system health aggregation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.v1.system_health import collect_system_health


class TestCollectSystemHealth:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.command = AsyncMock(return_value={
            "collections": 12,
            "objects": 45321,
            "dataSize": 134742016,
        })
        db.client.server_info = AsyncMock(return_value={"uptime": 1209600})
        return db

    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        r.info = AsyncMock(side_effect=lambda section: {
            "memory": {"used_memory_human": "24.3M", "used_memory": 25480396},
            "clients": {"connected_clients": 3},
            "server": {"uptime_in_seconds": 1209600},
        }.get(section, {}))
        r.ping = AsyncMock(return_value=True)
        return r

    async def test_returns_overall_status_operational(self, mock_db, mock_redis):
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=mock_redis),
        ):
            MockDB.get_database.return_value = mock_db
            result = await collect_system_health()

        assert result["overall_status"] == "operational"
        assert "mongodb" in result["services"]
        assert "redis" in result["services"]
        assert result["services"]["mongodb"]["status"] == "connected"
        assert result["services"]["redis"]["status"] == "connected"

    async def test_mongodb_failure_degrades_status(self, mock_redis):
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=mock_redis),
        ):
            MockDB.get_database.side_effect = RuntimeError("not connected")
            result = await collect_system_health()

        assert result["overall_status"] == "down"
        assert result["services"]["mongodb"]["status"] == "disconnected"

    async def test_redis_failure_degrades_status(self, mock_db):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("connection refused"))
        with (
            patch("app.api.v1.system_health.Database") as MockDB,
            patch("app.api.v1.system_health._get_redis_client", return_value=mock_redis),
        ):
            MockDB.get_database.return_value = mock_db
            result = await collect_system_health()

        assert result["overall_status"] == "down"
        assert result["services"]["redis"]["status"] == "disconnected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/unit/test_system_health.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement health aggregation**

Create `backend/app/api/v1/system_health.py`:

```python
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
        return {"status": "disconnected", "collections": 0, "total_documents": 0, "storage_size_mb": 0, "uptime_seconds": 0}


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
        return {"status": "disconnected", "used_memory_mb": 0, "connected_clients": 0, "uptime_seconds": 0}


def _check_telemetry() -> dict[str, dict[str, Any]]:
    """Gather telemetry pipeline stats from module singletons."""
    import app.modules.telemetry as telemetry_mod

    influxdb: dict[str, Any]
    if telemetry_mod._influxdb_service:
        raw = telemetry_mod._influxdb_service.get_stats()
        influxdb = {
            "status": "connected" if raw.get("connected") else "disconnected",
            "buffer_size": raw.get("buffer_size", 0),
            "buffer_capacity": raw.get("buffer_capacity", 0),
            "buffer_pct": round(raw["buffer_size"] / raw["buffer_capacity"] * 100, 1) if raw.get("buffer_capacity") else 0,
            "points_written": raw.get("points_written", 0),
            "points_dropped": raw.get("points_dropped", 0),
            "flush_count": raw.get("flush_count", 0),
            "last_flush_at": raw.get("last_flush_at", 0),
            "last_error": raw.get("last_error"),
        }
    else:
        influxdb = {"status": "disconnected", "buffer_size": 0, "buffer_capacity": 0, "buffer_pct": 0, "points_written": 0, "points_dropped": 0, "flush_count": 0, "last_flush_at": 0, "last_error": None}

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
        mist_ws = {"status": "disconnected", "connections": 0, "connections_ready": 0, "sites_subscribed": 0, "messages_received": 0, "messages_bridge_dropped": 0, "last_message_at": 0, "started_at": 0}

    ingestion: dict[str, Any]
    if telemetry_mod._ingestion_service:
        raw = telemetry_mod._ingestion_service.get_stats()
        ingestion = {
            "status": "running" if raw.get("running") else "stopped",
            "queue_size": raw.get("queue_size", 0),
            "queue_capacity": raw.get("queue_capacity", 0),
            "queue_pct": round(raw["queue_size"] / raw["queue_capacity"] * 100, 1) if raw.get("queue_capacity") else 0,
            "messages_processed": raw.get("messages_processed", 0),
            "points_extracted": raw.get("points_extracted", 0),
            "points_written": raw.get("points_written", 0),
            "points_filtered": raw.get("points_filtered", 0),
            "last_message_at": raw.get("last_message_at", 0),
        }
    else:
        ingestion = {"status": "stopped", "queue_size": 0, "queue_capacity": 0, "queue_pct": 0, "messages_processed": 0, "points_extracted": 0, "points_written": 0, "points_filtered": 0, "last_message_at": 0}

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
        mongo_result = {"status": "disconnected", "collections": 0, "total_documents": 0, "storage_size_mb": 0, "uptime_seconds": 0}
    if isinstance(redis_result, Exception):
        redis_result = {"status": "disconnected", "used_memory_mb": 0, "connected_clients": 0, "uptime_seconds": 0}

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

    # Derive overall status from worst service
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/unit/test_system_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/system_health.py backend/tests/unit/test_system_health.py
git commit -m "feat(admin): add system health aggregation module"
```

---

### Task 3: Add endpoint and wire up broadcaster

**Files:**
- Modify: `backend/app/api/v1/admin.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add endpoint to admin router**

In `backend/app/api/v1/admin.py`, add after the existing imports:

```python
from app.api.v1.system_health import collect_system_health
```

Add the endpoint (after the existing `get_system_stats` endpoint):

```python
@router.get("/admin/system-health", tags=["Admin"])
async def get_system_health(_current_user: User = Depends(require_admin)):
    """Get infrastructure health status (admin only)."""
    return await collect_system_health()
```

- [ ] **Step 2: Start broadcaster in app lifespan**

In `backend/app/main.py`, find the lifespan startup section (after scheduler and telemetry startup). Add:

```python
from app.api.v1.system_health import start_health_broadcaster, stop_health_broadcaster
```

In the startup block (after telemetry start):

```python
start_health_broadcaster()
```

In the shutdown block (before telemetry stop):

```python
await stop_health_broadcaster()
```

- [ ] **Step 3: Test manually**

Run: `cd backend && .venv/bin/python -m app.main`
Then: `curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/admin/system-health | python3 -m json.tool`

Expected: JSON with `overall_status`, `checked_at`, and `services` dict containing all 7 services.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/admin.py backend/app/main.py
git commit -m "feat(admin): add GET /admin/system-health endpoint and broadcaster"
```

---

### Task 4: Frontend TypeScript interfaces

**Files:**
- Modify: `frontend/src/app/core/models/admin.model.ts`

- [ ] **Step 1: Add SystemHealth interfaces**

Append to `frontend/src/app/core/models/admin.model.ts`:

```typescript
export interface ServiceHealth {
  status: string;
  [key: string]: unknown;
}

export interface MongoHealth extends ServiceHealth {
  collections: number;
  total_documents: number;
  storage_size_mb: number;
  uptime_seconds: number;
}

export interface RedisHealth extends ServiceHealth {
  used_memory_mb: number;
  connected_clients: number;
  uptime_seconds: number;
}

export interface InfluxHealth extends ServiceHealth {
  buffer_size: number;
  buffer_capacity: number;
  buffer_pct: number;
  points_written: number;
  points_dropped: number;
  flush_count: number;
  last_flush_at: number;
  last_error: string | null;
}

export interface MistWsHealth extends ServiceHealth {
  connections: number;
  connections_ready: number;
  sites_subscribed: number;
  messages_received: number;
  messages_bridge_dropped: number;
  last_message_at: number;
  started_at: number;
}

export interface IngestionHealth extends ServiceHealth {
  queue_size: number;
  queue_capacity: number;
  queue_pct: number;
  messages_processed: number;
  points_extracted: number;
  points_written: number;
  points_filtered: number;
  last_message_at: number;
}

export interface AppWsHealth {
  connected_clients: number;
  active_channels: number;
  total_subscriptions: number;
}

export interface SchedulerHealth extends ServiceHealth {
  scheduled_jobs: number;
}

export interface SystemHealth {
  overall_status: 'operational' | 'degraded' | 'down';
  checked_at: number;
  services: {
    mongodb: MongoHealth;
    redis: RedisHealth;
    influxdb: InfluxHealth;
    mist_websocket: MistWsHealth;
    ingestion: IngestionHealth;
    app_websocket: AppWsHealth;
    scheduler: SchedulerHealth;
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/core/models/admin.model.ts
git commit -m "feat(admin): add SystemHealth TypeScript interfaces"
```

---

### Task 5: Frontend admin service method

**Files:**
- Modify: `frontend/src/app/core/services/admin.service.ts`

- [ ] **Step 1: Add getSystemHealth method**

Import `SystemHealth` and add to `AdminService`:

```typescript
import { SystemHealth } from '../models/admin.model';
```

Add method:

```typescript
getSystemHealth(): Observable<SystemHealth> {
  return this.api.get<SystemHealth>('/admin/system-health');
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/core/services/admin.service.ts
git commit -m "feat(admin): add getSystemHealth() to AdminService"
```

---

### Task 6: Stats component — data layer (signals + WS subscription)

**Files:**
- Modify: `frontend/src/app/features/admin/stats/stats.component.ts`

- [ ] **Step 1: Add health data signals and WS subscription**

Add imports:

```typescript
import { DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SystemHealth } from '../../../core/models/admin.model';
import { AdminService } from '../../../core/services/admin.service';
import { WebSocketService } from '../../../core/services/websocket.service';
```

Add to the component class:

```typescript
private readonly adminService = inject(AdminService);
private readonly wsService = inject(WebSocketService);
private readonly destroyRef = inject(DestroyRef);

health = signal<SystemHealth | null>(null);
healthLoading = signal(true);
```

In `ngOnInit()`, add after existing stat fetches:

```typescript
// Fetch initial system health
this.adminService.getSystemHealth().subscribe({
  next: (h) => {
    this.health.set(h);
    this.healthLoading.set(false);
  },
  error: () => this.healthLoading.set(false),
});

// Subscribe to real-time health updates
this.wsService
  .subscribe('system:health')
  .pipe(takeUntilDestroyed(this.destroyRef))
  .subscribe((msg) => {
    if (msg.type === 'health_update' && msg.data) {
      this.health.set(msg.data as SystemHealth);
    }
  });
```

Also add computed helpers for the KPI tiles:

```typescript
servicesUp = computed(() => {
  const h = this.health();
  if (!h) return '—';
  const svc = h.services;
  const checks = [svc.mongodb.status, svc.redis.status, svc.influxdb.status, svc.mist_websocket.status];
  const up = checks.filter((s) => s === 'connected' || s === 'running' || s === 'active').length;
  return `${up}/${checks.length}`;
});

overallStatusClass = computed(() => {
  const h = this.health();
  if (!h) return '';
  return h.overall_status === 'operational' ? 'status-ok' : h.overall_status === 'degraded' ? 'status-warn' : 'status-error';
});

overallStatusText = computed(() => {
  const h = this.health();
  if (!h) return '';
  return h.overall_status === 'operational' ? 'All Systems Operational' : h.overall_status === 'degraded' ? 'Degraded Performance' : 'Service Disruption';
});
```

Add the module imports to the component's `imports` array:

```typescript
MatExpansionModule, MatProgressBarModule
```

(from `@angular/material/expansion` and `@angular/material/progress-bar`)

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/features/admin/stats/stats.component.ts
git commit -m "feat(admin): add health signals and WS subscription to stats component"
```

---

### Task 7: Stats component — template (ribbon, KPIs, service panels)

**Files:**
- Modify: `frontend/src/app/features/admin/stats/stats.component.html`

- [ ] **Step 1: Add health sections above existing grid**

Replace the entire template with the health sections prepended before the existing `stats-grid`. Insert BEFORE the `@if (loading())` block:

```html
<!-- System Health -->
@if (healthLoading()) {
  <mat-progress-bar mode="indeterminate"></mat-progress-bar>
} @else if (health(); as health) {
  <!-- Status Ribbon -->
  <div class="status-ribbon" [class]="overallStatusClass()">
    <span class="status-dot"></span>
    <span class="status-text">{{ overallStatusText() }}</span>
    <span class="status-time">Updated {{ health.checked_at * 1000 | date:'mediumTime' }}</span>
  </div>

  <!-- KPI Tiles -->
  <div class="kpi-grid">
    <div class="kpi-tile">
      <span class="kpi-value">{{ servicesUp() }}</span>
      <span class="kpi-label">Services Up</span>
    </div>
    <div class="kpi-tile">
      <span class="kpi-value">{{ health.services.mist_websocket.sites_subscribed }}</span>
      <span class="kpi-label">Sites</span>
    </div>
    <div class="kpi-tile">
      <span class="kpi-value">{{ health.services.influxdb.buffer_pct }}%</span>
      <span class="kpi-label">Buffer</span>
    </div>
    <div class="kpi-tile">
      <span class="kpi-value">{{ health.services.influxdb.points_dropped }}</span>
      <span class="kpi-label" [class.kpi-error]="health.services.influxdb.points_dropped > 0">Errors</span>
    </div>
    <div class="kpi-tile">
      <span class="kpi-value">{{ health.services.app_websocket.connected_clients }}</span>
      <span class="kpi-label">WS Clients</span>
    </div>
  </div>

  <!-- Service Detail Panels -->
  <mat-accordion multi>
    <!-- Infrastructure -->
    <mat-expansion-panel expanded>
      <mat-expansion-panel-header>
        <mat-panel-title>Infrastructure</mat-panel-title>
      </mat-expansion-panel-header>
      <div class="service-cards">
        <!-- MongoDB -->
        <mat-card [class]="'service-card status-' + health.services.mongodb.status">
          <mat-card-header>
            <mat-icon mat-card-avatar>storage</mat-icon>
            <mat-card-title>MongoDB</mat-card-title>
            <app-status-badge [status]="health.services.mongodb.status"></app-status-badge>
          </mat-card-header>
          <mat-card-content>
            <div class="stat-row"><span>Collections</span><strong>{{ health.services.mongodb.collections }}</strong></div>
            <div class="stat-row"><span>Documents</span><strong>{{ health.services.mongodb.total_documents | number }}</strong></div>
            <div class="stat-row"><span>Storage</span><strong>{{ health.services.mongodb.storage_size_mb }} MB</strong></div>
          </mat-card-content>
        </mat-card>

        <!-- Redis -->
        <mat-card [class]="'service-card status-' + health.services.redis.status">
          <mat-card-header>
            <mat-icon mat-card-avatar>memory</mat-icon>
            <mat-card-title>Redis</mat-card-title>
            <app-status-badge [status]="health.services.redis.status"></app-status-badge>
          </mat-card-header>
          <mat-card-content>
            <div class="stat-row"><span>Memory</span><strong>{{ health.services.redis.used_memory_mb }} MB</strong></div>
            <div class="stat-row"><span>Clients</span><strong>{{ health.services.redis.connected_clients }}</strong></div>
          </mat-card-content>
        </mat-card>
      </div>
    </mat-expansion-panel>

    <!-- Telemetry Pipeline -->
    <mat-expansion-panel expanded>
      <mat-expansion-panel-header>
        <mat-panel-title>Telemetry Pipeline</mat-panel-title>
      </mat-expansion-panel-header>
      <div class="service-cards">
        <!-- InfluxDB -->
        <mat-card [class]="'service-card status-' + health.services.influxdb.status">
          <mat-card-header>
            <mat-icon mat-card-avatar>show_chart</mat-icon>
            <mat-card-title>InfluxDB</mat-card-title>
            <app-status-badge [status]="health.services.influxdb.status"></app-status-badge>
          </mat-card-header>
          <mat-card-content>
            <div class="stat-row">
              <span>Buffer</span>
              <strong>{{ health.services.influxdb.buffer_size }} / {{ health.services.influxdb.buffer_capacity }}</strong>
            </div>
            <mat-progress-bar mode="determinate" [value]="health.services.influxdb.buffer_pct"
              [class]="health.services.influxdb.buffer_pct > 90 ? 'buffer-critical' : health.services.influxdb.buffer_pct > 70 ? 'buffer-warn' : 'buffer-ok'">
            </mat-progress-bar>
            <div class="stat-row"><span>Written</span><strong>{{ health.services.influxdb.points_written | number }}</strong></div>
            <div class="stat-row"><span>Dropped</span><strong>{{ health.services.influxdb.points_dropped }}</strong></div>
            @if (health.services.influxdb.last_error) {
              <div class="stat-row error-row"><span>Last Error</span><strong>{{ health.services.influxdb.last_error }}</strong></div>
            }
          </mat-card-content>
        </mat-card>

        <!-- Mist WebSocket -->
        <mat-card [class]="'service-card status-' + health.services.mist_websocket.status">
          <mat-card-header>
            <mat-icon mat-card-avatar>cell_tower</mat-icon>
            <mat-card-title>Mist WebSocket</mat-card-title>
            <app-status-badge [status]="health.services.mist_websocket.status"></app-status-badge>
          </mat-card-header>
          <mat-card-content>
            <div class="stat-row"><span>Connections</span><strong>{{ health.services.mist_websocket.connections_ready }} / {{ health.services.mist_websocket.connections }}</strong></div>
            <div class="stat-row"><span>Sites</span><strong>{{ health.services.mist_websocket.sites_subscribed }}</strong></div>
            <div class="stat-row"><span>Messages</span><strong>{{ health.services.mist_websocket.messages_received | number }}</strong></div>
            <div class="stat-row"><span>Dropped</span><strong>{{ health.services.mist_websocket.messages_bridge_dropped }}</strong></div>
          </mat-card-content>
        </mat-card>

        <!-- Ingestion -->
        <mat-card [class]="'service-card status-' + health.services.ingestion.status">
          <mat-card-header>
            <mat-icon mat-card-avatar>filter_alt</mat-icon>
            <mat-card-title>Ingestion</mat-card-title>
            <app-status-badge [status]="health.services.ingestion.status"></app-status-badge>
          </mat-card-header>
          <mat-card-content>
            <div class="stat-row">
              <span>Queue</span>
              <strong>{{ health.services.ingestion.queue_size }} / {{ health.services.ingestion.queue_capacity }}</strong>
            </div>
            <mat-progress-bar mode="determinate" [value]="health.services.ingestion.queue_pct"
              [class]="health.services.ingestion.queue_pct > 90 ? 'buffer-critical' : health.services.ingestion.queue_pct > 70 ? 'buffer-warn' : 'buffer-ok'">
            </mat-progress-bar>
            <div class="stat-row"><span>Processed</span><strong>{{ health.services.ingestion.messages_processed | number }}</strong></div>
            <div class="stat-row"><span>Written</span><strong>{{ health.services.ingestion.points_written | number }}</strong></div>
            <div class="stat-row"><span>Filtered</span><strong>{{ health.services.ingestion.points_filtered | number }}</strong></div>
          </mat-card-content>
        </mat-card>
      </div>
    </mat-expansion-panel>

    <!-- App WebSocket & Workers -->
    <mat-expansion-panel expanded>
      <mat-expansion-panel-header>
        <mat-panel-title>App WebSocket & Workers</mat-panel-title>
      </mat-expansion-panel-header>
      <div class="service-cards">
        <mat-card class="service-card status-connected">
          <mat-card-header>
            <mat-icon mat-card-avatar>sync_alt</mat-icon>
            <mat-card-title>App WebSocket</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="stat-row"><span>Clients</span><strong>{{ health.services.app_websocket.connected_clients }}</strong></div>
            <div class="stat-row"><span>Channels</span><strong>{{ health.services.app_websocket.active_channels }}</strong></div>
            <div class="stat-row"><span>Subscriptions</span><strong>{{ health.services.app_websocket.total_subscriptions }}</strong></div>
          </mat-card-content>
        </mat-card>

        <mat-card [class]="'service-card status-' + health.services.scheduler.status">
          <mat-card-header>
            <mat-icon mat-card-avatar>engineering</mat-icon>
            <mat-card-title>Scheduler</mat-card-title>
            <app-status-badge [status]="health.services.scheduler.status"></app-status-badge>
          </mat-card-header>
          <mat-card-content>
            <div class="stat-row"><span>Scheduled Jobs</span><strong>{{ health.services.scheduler.scheduled_jobs }}</strong></div>
          </mat-card-content>
        </mat-card>
      </div>
    </mat-expansion-panel>
  </mat-accordion>
}

<!-- Existing business stats (unchanged below) -->
```

Keep ALL existing template content (the `@if (loading())` ... `stats-grid` block) exactly as-is below the new health sections.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/features/admin/stats/stats.component.html
git commit -m "feat(admin): add health ribbon, KPI tiles, and service panels to stats template"
```

---

### Task 8: Stats component — styles

**Files:**
- Modify: `frontend/src/app/features/admin/stats/stats.component.scss`

- [ ] **Step 1: Add styles for health sections**

Append to the existing SCSS:

```scss
// Status Ribbon
.status-ribbon {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-radius: var(--app-radius);
  margin-bottom: 24px;
  font-weight: 500;

  &.status-ok { background: var(--app-success-bg); color: var(--app-success); }
  &.status-warn { background: var(--app-warning-bg); color: var(--app-warning); }
  &.status-error { background: var(--app-error-status-bg); color: var(--app-error-status); }

  .status-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: currentColor;
    flex-shrink: 0;
  }

  .status-text { flex: 1; }
  .status-time {
    font-size: 12px;
    opacity: 0.7;
    font-weight: 400;
  }
}

// KPI Tiles
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px;
  border-radius: var(--app-radius);
  background: var(--mat-sys-surface-container);
  border: 1px solid var(--mat-sys-outline-variant);

  .kpi-value {
    font-size: 28px;
    font-weight: 700;
    line-height: 1.2;
  }

  .kpi-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--mat-sys-on-surface-variant);
    margin-top: 4px;
  }

  .kpi-error { color: var(--app-error-status); }
}

// Service Cards inside expansion panels
.service-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  padding: 8px 0;
}

.service-card {
  border-left: 4px solid var(--app-neutral);

  &.status-connected, &.status-running, &.status-active { border-left-color: var(--app-success); }
  &.status-degraded { border-left-color: var(--app-warning); }
  &.status-disconnected, &.status-stopped { border-left-color: var(--app-error-status); }

  mat-card-header {
    app-status-badge { margin-left: auto; }
  }

  mat-progress-bar {
    margin: 8px 0;
    border-radius: 4px;

    &.buffer-ok { --mdc-linear-progress-active-indicator-color: var(--app-success); }
    &.buffer-warn { --mdc-linear-progress-active-indicator-color: var(--app-warning); }
    &.buffer-critical { --mdc-linear-progress-active-indicator-color: var(--app-error-status); }
  }
}

.error-row strong {
  color: var(--app-error-status);
  font-size: 12px;
  word-break: break-all;
}

// Accordion spacing
mat-accordion {
  margin-bottom: 32px;

  mat-expansion-panel {
    margin-bottom: 8px;
    box-shadow: var(--app-shadow-sm) !important;
    border-radius: var(--app-radius) !important;
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/features/admin/stats/stats.component.scss
git commit -m "feat(admin): add styles for health ribbon, KPIs, service cards"
```

---

### Task 9: Verify end-to-end

- [ ] **Step 1: Run backend tests**

```bash
cd backend
.venv/bin/pytest tests/unit/test_websocket_stats.py tests/unit/test_system_health.py -v
.venv/bin/ruff check app/api/v1/system_health.py app/core/websocket.py
```

Expected: all pass, lint clean.

- [ ] **Step 2: Run frontend build**

```bash
cd frontend
npx ng build
```

Expected: clean build, no errors.

- [ ] **Step 3: Manual verification**

1. Start backend + frontend
2. Navigate to Admin > System Stats
3. Verify: status ribbon (green/amber/red), KPI tiles with live numbers, expandable panels with service cards
4. Wait 10s — verify values update via WebSocket
5. Stop Redis/InfluxDB — verify status changes to red/down
6. Existing business stats (Users, Workflows, etc.) still display below

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(admin): system health dashboard with real-time updates"
```

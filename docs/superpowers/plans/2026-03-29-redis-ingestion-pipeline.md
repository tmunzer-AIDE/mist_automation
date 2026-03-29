# Redis-Backed Ingestion Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple data ingestion (webhook HTTP endpoint, telemetry WebSocket reader) from processing by using Redis Streams as a durable buffer — enabling crash resilience, burst absorption, and future horizontal scaling.

**Architecture:** The webhook gateway and telemetry WS reader become thin producers that validate/ack incoming data and publish to Redis Streams. Async consumer loops (running as asyncio tasks in the same process) read from these streams, dispatch to existing processing functions, and acknowledge on completion. Dead Celery code is removed. APScheduler gains a Redis-backed job store for restart resilience.

**Tech Stack:** Redis 7 (Streams, consumer groups), `redis.asyncio` (async client, already installed as `redis>=5.2.0`), `redis` sync client (for APScheduler + WS thread producer), APScheduler `RedisJobStore`.

---

## Current Architecture (reference for future sessions)

### Webhook Ingestion — Current Flow

```
POST /webhooks/mist  (app/api/v1/webhooks.py:114)
  │
  ├─ SystemConfig.get_config()                    [MongoDB read]
  ├─ HMAC signature validation                     [pure]
  ├─ IP allowlist check                            [pure]
  │
  │  for each event in payload["events"]:
  │    ├─ enrich_event() + extract_event_fields()  [pure, from app/core/webhook_extractor.py]
  │    ├─ WebhookEvent(...).insert()               [MongoDB write, dedup by webhook_id unique index]
  │    │
  │    ├─ create_background_task(process_webhook(...))        [ALWAYS — automation]
  │    ├─ create_background_task(handle_device_event(...))    [device-events only — impact analysis]
  │    └─ ws_manager.broadcast("webhook:monitor", ...)        [WebSocket to frontend]
  │
  └─ [audits only] await process_backup_webhook(payload, config)
            └─ create_background_task(perform_incremental_backup(...))
```

**Problem at scale:** `create_background_task()` runs processing on the same event loop as HTTP request handling. A burst of 500 webhooks saturates the loop — Mist gets slow/no responses and retries or drops.

**Key functions involved:**
- `process_webhook(webhook_id, webhook_type, payload, *, event_type)` — `app/modules/automation/workers/webhook_worker.py:49` — queries MongoDB for matching workflows, executes them
- `handle_device_event(webhook_event_id, event_type, enriched_payload)` — `app/modules/impact_analysis/workers/event_handler.py:116` — routes to impact analysis session lifecycle
- `process_backup_webhook(payload, config)` — `app/modules/backup/webhook_handler.py:16` — validates org_id, filters heartbeats, dispatches `perform_incremental_backup`
- `perform_incremental_backup(org_id, audit_events)` — `app/modules/backup/workers.py:690` — processes audit events into config backups
- `create_background_task(coro, name)` — `app/core/tasks.py:13` — thin wrapper around `asyncio.create_task()` with error logging

**Routing logic (webhooks.py:171-176):**
```python
routed_to = ["automation"]              # always
if topic == "audits":
    routed_to.append("backup")
if webhook_type == "device-events":
    routed_to.append("impact_analysis")
```

**WebhookEvent model** — `app/modules/automation/models/webhook.py` — Beanie Document with fields: `webhook_type`, `webhook_id` (unique index), `payload` (enriched dict), `event_type`, `org_id`, `site_id`, `device_mac`, `processed`, `routed_to`, `matched_workflows`, `executions_triggered`, etc.

**Replay endpoint** — `POST /webhooks/events/{id}/replay` (webhooks.py:400) — resets `processed=False`, calls `create_background_task(process_webhook(...))`. Only dispatches to automation.

### Telemetry WebSocket Ingestion — Current Flow

```
Mist Cloud WSS
      │
      v
MistWsManager._on_ws_message()     [background THREAD, one per 1000 sites]
      │  loop.call_soon_threadsafe()
      v
asyncio.Queue(maxsize=10_000)       [thread→async bridge, drops on full]
      │
      v
IngestionService._consume_loop()    [asyncio task]
      ├─ extract_points()            [pure — per device type]
      ├─ CoVFilter.should_write()    [deadband filter]
      ├─ LatestValueCache.update()   [always, every message]
      ├─ InfluxDBService.write_points()  [enqueues into second buffer]
      │        │
      │        v
      │   asyncio.Queue(maxsize=10_000)  [InfluxDB write buffer, drops on full]
      │        │
      │   _flush_loop()              [every 10s, drains 500-point batches]
      │        v
      │   InfluxDB 2.7
      │
      └─ ws_manager.broadcast("telemetry:device:{mac}", event)
```

**Problem at scale:** Two bounded queues with silent `put_nowait` drops. No crash resilience — process restart loses all buffered data. The `call_soon_threadsafe` bridge is fragile.

**Key files:**
- `app/modules/telemetry/services/mist_ws_manager.py` — WS connections, `_on_ws_message` (thread callback, line 50), `_safe_enqueue` (line 72, `put_nowait` with drop)
- `app/modules/telemetry/services/ingestion_service.py` — `_consume_loop` (line 443), `_process_message` (line 456), creates `asyncio.Queue(10_000)` at line 394
- `app/modules/telemetry/services/influxdb_service.py` — `write_points` (line 90, `put_nowait`), `_flush_loop` (line 100, 10s interval, 500-batch)
- `app/modules/telemetry/services/lifecycle.py` — startup wiring: creates singletons, passes queue from IngestionService to MistWsManager

**WS message shape from Mist:** `{"event": "data", "channel": "/sites/{uuid}/stats/devices", "data": "<JSON string>"}`

### Dead Celery Code (to remove)

- `app/core/celery_app.py` — Celery app instance, never started as worker
- `app/modules/automation/workers/webhook_worker.py:30-46` — `process_webhook_task` Celery decorator + `asyncio.run()` bridge
- `app/modules/backup/workers.py:24-42` — `perform_backup_task` Celery task (never called via `.delay()`)
- `app/modules/backup/workers.py:191-210` — `cleanup_old_backups_task` Celery task (never called)
- `app/modules/backup/workers.py:268-288` — `queue_backup()` function (calls `.delay()`, but nothing calls `queue_backup()`)
- `app/modules/backup/workers.py:290-310` — `schedule_periodic_backups()` function (sets `beat_schedule`, never called)
- `app/config.py:71-72` — `celery_broker_url`, `celery_result_backend` settings

### Redis Infrastructure — Current State

- Redis 7 Alpine in docker-compose, port 6379, no auth, volume `redis_data`
- `redis_url: str = "redis://localhost:6379/0"` in config (DB 0)
- `redis_max_connections: int = 50` in config (never used — no pool exists)
- Only consumer: `app/api/v1/system_health.py:20-62` — ad-hoc `aioredis.from_url()` per health check, PING + INFO
- No `app/core/redis.py` or connection pool singleton
- `redis>=5.2.0` in requirements (includes `redis.asyncio`)

### APScheduler — Current State

- `app/modules/automation/workers/scheduler.py` — `AsyncIOScheduler` with `MemoryJobStore` (line 28)
- Jobs rebuilt from MongoDB on every restart (`_load_cron_workflows`, `_load_backup_schedule`)
- `misfire_grace_time: 300` — 5-minute catch-up window
- Started from `main.py:66` via `app/workers/__init__.py` re-export

---

## Target Architecture

```
                    ┌─────────────────────────────────────────────────┐
                    │                  Redis 7                         │
                    │                                                  │
  POST /webhooks/mist ──publish──▶ Stream: webhook:automation ──▶ Consumer ──▶ process_webhook()
         │                         Stream: webhook:backup     ──▶ Consumer ──▶ perform_incremental_backup()
         │                         Stream: webhook:impact     ──▶ Consumer ──▶ handle_device_event()
         │
         ├─ validate (HMAC, IP)
         ├─ WebhookEvent.insert() [MongoDB — unchanged]
         ├─ ws_manager.broadcast() [frontend WS — unchanged]
         └─ return 200 [fast — no processing on event loop]

  Mist WSS ──thread──▶ Stream: telemetry:ingestion ──▶ Consumer ──▶ IngestionService._process_message()
         │                                                              ├─ extract + CoV filter
         │  (redis-py sync client,                                      ├─ InfluxDB write (keep existing buffer)
         │   thread-safe, no                                            └─ WS broadcast
         │   call_soon_threadsafe)

  APScheduler ──▶ RedisJobStore (DB 0) ──▶ jobs survive restart
```

**Key design decisions:**
1. **Redis Streams** (not Lists) — consumer groups enable future horizontal scaling, built-in ack/nack, message persistence with configurable TTL
2. **Same-process consumers** — asyncio tasks reading from streams, not separate worker processes. Adds crash resilience and burst absorption without deployment complexity. Separate workers can be added later with zero code changes (just start another consumer with the same group).
3. **Existing processing functions unchanged** — `process_webhook()`, `handle_device_event()`, `perform_incremental_backup()` keep their signatures. Only the dispatch mechanism changes.
4. **Telemetry: Redis replaces the first asyncio.Queue only** — the InfluxDB write buffer (second queue) stays as-is since it's already well-tuned (10s flush, 500-batch).
5. **Graceful degradation** — if Redis is down, webhook gateway falls back to `create_background_task()` (current behavior). Telemetry WS manager falls back to asyncio.Queue.

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `app/core/redis_pool.py` | Async + sync Redis connection pools, startup/shutdown, stream helper methods (publish, ensure_group) |
| `app/core/stream_consumer.py` | Generic `StreamConsumer` class — reads from a Redis Stream consumer group, calls a handler, acks on success |

### Modified Files

| File | What Changes |
|------|-------------|
| `app/config.py` | Remove `celery_broker_url`, `celery_result_backend`. Add `redis_stream_block_ms`, `redis_stream_batch_size`, `redis_stream_max_len` |
| `app/main.py` | Start/stop Redis pool + stream consumers in lifespan. Remove Celery imports. |
| `app/api/v1/webhooks.py` | Replace `create_background_task()` calls with Redis Stream publish. Add fallback. |
| `app/api/v1/system_health.py` | Use shared Redis pool instead of ad-hoc client. Add stream stats (length, pending, lag). |
| `app/modules/backup/webhook_handler.py` | `process_backup_webhook` returns validated events dict for Redis publish instead of calling `create_background_task` internally |
| `app/modules/telemetry/services/mist_ws_manager.py` | Replace `asyncio.Queue` + `call_soon_threadsafe` with sync Redis `XADD` |
| `app/modules/telemetry/services/ingestion_service.py` | Replace `asyncio.Queue` consumer with Redis Stream consumer |
| `app/modules/telemetry/services/lifecycle.py` | Wire Redis pool into telemetry pipeline startup |
| `app/modules/automation/workers/scheduler.py` | Replace `MemoryJobStore` with `RedisJobStore` |
| `app/workers/__init__.py` | No change needed (only re-exports scheduler functions) |

### Deleted Files

| File | Reason |
|------|--------|
| `app/core/celery_app.py` | Celery is dead code — no worker ever runs |

### Dead Code Removal (within modified files)

| File | Lines/Functions to Remove |
|------|--------------------------|
| `app/modules/automation/workers/webhook_worker.py` | `process_webhook_task` Celery decorator (lines 30-46), `celery_app` import |
| `app/modules/backup/workers.py` | `perform_backup_task` (lines 24-42), `cleanup_old_backups_task` (lines 191-210), `queue_backup()` (lines 268-288), `schedule_periodic_backups()` (lines 290-310), `celery_app` import |
| `requirements.txt` / `pyproject.toml` | Remove `celery>=5.4.0` dependency |

---

## Task 1: Redis Connection Pool Singleton

**Files:**
- Create: `backend/app/core/redis_pool.py`
- Modify: `backend/app/config.py` (add stream settings, remove Celery settings)

This task creates the shared Redis infrastructure used by all subsequent tasks.

- [ ] **Step 1: Add stream config settings**

In `backend/app/config.py`, remove the Celery settings and add Redis Stream settings:

```python
# REMOVE these two lines (around line 71-72):
# celery_broker_url: str = "redis://localhost:6379/1"
# celery_result_backend: str = "redis://localhost:6379/2"

# ADD these after redis_max_connections (around line 55):
redis_stream_block_ms: int = 2000          # XREADGROUP block timeout
redis_stream_batch_size: int = 50          # messages per XREADGROUP call
redis_stream_max_len: int = 100_000        # MAXLEN cap per stream (approximate)
```

- [ ] **Step 2: Create the Redis pool module**

Create `backend/app/core/redis_pool.py`:

```python
"""
Shared Redis connection pools (async + sync) and stream helpers.

Usage:
    from app.core.redis_pool import redis_pool

    # In async context:
    client = redis_pool.async_client()
    await client.ping()

    # In thread context (WS manager, APScheduler):
    client = redis_pool.sync_client()
    client.ping()

    # Publish to a stream:
    await redis_pool.stream_publish("webhook:automation", {"event_id": "abc", ...})
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis as sync_redis
import redis.asyncio as async_redis

from app.config import settings

logger = logging.getLogger(__name__)


class RedisPool:
    """Manages async and sync Redis connection pools with stream helpers."""

    def __init__(self) -> None:
        self._async_pool: async_redis.ConnectionPool | None = None
        self._sync_pool: sync_redis.ConnectionPool | None = None
        self._started = False

    async def start(self) -> None:
        """Initialize connection pools. Call once at app startup."""
        if self._started:
            return
        self._async_pool = async_redis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            decode_responses=True,
        )
        self._sync_pool = sync_redis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            decode_responses=True,
        )
        # Verify connectivity
        async with async_redis.Redis(connection_pool=self._async_pool) as client:
            await client.ping()
        self._started = True
        logger.info("redis_pool_started", extra={"url": settings.redis_url})

    async def stop(self) -> None:
        """Close connection pools. Call once at app shutdown."""
        if self._async_pool:
            await self._async_pool.aclose()
            self._async_pool = None
        if self._sync_pool:
            self._sync_pool.close()
            self._sync_pool = None
        self._started = False
        logger.info("redis_pool_stopped")

    @property
    def is_started(self) -> bool:
        return self._started

    def async_client(self) -> async_redis.Redis:
        """Get an async Redis client from the shared pool."""
        if not self._async_pool:
            raise RuntimeError("RedisPool not started — call await redis_pool.start() first")
        return async_redis.Redis(connection_pool=self._async_pool)

    def sync_client(self) -> sync_redis.Redis:
        """Get a sync Redis client from the shared pool. Thread-safe."""
        if not self._sync_pool:
            raise RuntimeError("RedisPool not started — call await redis_pool.start() first")
        return sync_redis.Redis(connection_pool=self._sync_pool)

    async def ensure_consumer_group(self, stream: str, group: str) -> None:
        """Create a consumer group if it doesn't exist. Creates the stream if needed."""
        client = self.async_client()
        try:
            await client.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info("redis_consumer_group_created", extra={"stream": stream, "group": group})
        except async_redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass  # Group already exists
            else:
                raise
        finally:
            await client.aclose()

    async def stream_publish(self, stream: str, fields: dict[str, str], max_len: int | None = None) -> str:
        """Publish a message to a Redis Stream. Returns the message ID."""
        if max_len is None:
            max_len = settings.redis_stream_max_len
        client = self.async_client()
        try:
            msg_id = await client.xadd(stream, fields, maxlen=max_len, approximate=True)
            return msg_id
        finally:
            await client.aclose()

    async def get_stream_info(self, stream: str) -> dict[str, Any]:
        """Get stream length and consumer group info for health monitoring."""
        client = self.async_client()
        try:
            info: dict[str, Any] = {"exists": False}
            try:
                length = await client.xlen(stream)
                info = {"exists": True, "length": length, "groups": []}
                groups = await client.xinfo_groups(stream)
                for g in groups:
                    info["groups"].append({
                        "name": g.get("name"),
                        "consumers": g.get("consumers"),
                        "pending": g.get("pending"),
                        "lag": g.get("lag"),
                    })
            except async_redis.ResponseError:
                pass  # Stream doesn't exist yet
            return info
        finally:
            await client.aclose()


# Module-level singleton
redis_pool = RedisPool()
```

- [ ] **Step 3: Verify Redis pool starts**

Run from the backend directory:
```bash
cd backend && python -c "
import asyncio
from app.core.redis_pool import redis_pool

async def test():
    await redis_pool.start()
    client = redis_pool.async_client()
    assert await client.ping()
    await client.aclose()
    await redis_pool.stop()
    print('OK: Redis pool works')

asyncio.run(test())
"
```

Expected: `OK: Redis pool works`

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/redis_pool.py backend/app/config.py
git commit -m "feat: add Redis connection pool singleton and stream config

Remove dead Celery config (celery_broker_url, celery_result_backend).
Add Redis Stream settings for the ingestion pipeline."
```

---

## Task 2: Generic Stream Consumer

**Files:**
- Create: `backend/app/core/stream_consumer.py`

A reusable consumer class that reads from a Redis Stream consumer group, calls a handler function, and acks on success. Used by webhook consumers (Task 5) and telemetry consumer (Task 8).

- [ ] **Step 1: Create the StreamConsumer class**

Create `backend/app/core/stream_consumer.py`:

```python
"""
Generic Redis Stream consumer with consumer groups.

Usage:
    async def my_handler(msg_id: str, fields: dict[str, str]) -> None:
        # process the message
        ...

    consumer = StreamConsumer(
        stream="webhook:automation",
        group="automation-workers",
        handler=my_handler,
        redis_pool=redis_pool,
    )
    await consumer.start()
    # ... later ...
    await consumer.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import redis.asyncio as async_redis

from app.config import settings
from app.core.redis_pool import RedisPool

logger = logging.getLogger(__name__)

# Type for handler: receives (message_id, fields_dict), returns None
MessageHandler = Callable[[str, dict[str, str]], Awaitable[None]]


class StreamConsumer:
    """Reads from a Redis Stream consumer group, dispatches to a handler, acks on success."""

    def __init__(
        self,
        stream: str,
        group: str,
        handler: MessageHandler,
        pool: RedisPool,
        consumer_name: str = "worker-1",
        batch_size: int | None = None,
        block_ms: int | None = None,
    ) -> None:
        self.stream = stream
        self.group = group
        self.handler = handler
        self._pool = pool
        self.consumer_name = consumer_name
        self._batch_size = batch_size or settings.redis_stream_batch_size
        self._block_ms = block_ms or settings.redis_stream_block_ms
        self._task: asyncio.Task | None = None
        self._running = False
        self._messages_processed = 0
        self._messages_failed = 0

    async def start(self) -> None:
        """Ensure consumer group exists and start the consume loop."""
        await self._pool.ensure_consumer_group(self.stream, self.group)
        # First, reclaim any pending messages from previous runs
        self._running = True
        self._task = asyncio.create_task(self._consume_loop(), name=f"consumer-{self.stream}")
        logger.info(
            "stream_consumer_started",
            extra={"stream": self.stream, "group": self.group, "consumer": self.consumer_name},
        )

    async def stop(self) -> None:
        """Stop the consume loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(
            "stream_consumer_stopped",
            extra={
                "stream": self.stream,
                "processed": self._messages_processed,
                "failed": self._messages_failed,
            },
        )

    async def _consume_loop(self) -> None:
        """Main loop: XREADGROUP → handler → XACK."""
        # Phase 1: Process any pending messages from previous runs (crash recovery)
        await self._process_pending()

        # Phase 2: Read new messages
        while self._running:
            try:
                client = self._pool.async_client()
                try:
                    results = await client.xreadgroup(
                        groupname=self.group,
                        consumername=self.consumer_name,
                        streams={self.stream: ">"},  # ">" = only new messages
                        count=self._batch_size,
                        block=self._block_ms,
                    )
                finally:
                    await client.aclose()

                if not results:
                    continue  # block timeout, no messages

                for _stream_name, messages in results:
                    for msg_id, fields in messages:
                        await self._handle_message(msg_id, fields)

            except asyncio.CancelledError:
                raise
            except async_redis.ConnectionError:
                logger.warning("stream_consumer_redis_disconnected", extra={"stream": self.stream})
                await asyncio.sleep(1)  # back off on connection loss
            except Exception:
                logger.exception("stream_consumer_loop_error", extra={"stream": self.stream})
                await asyncio.sleep(0.1)

    async def _process_pending(self) -> None:
        """Reclaim and process messages that were delivered but not acked (crash recovery)."""
        logger.info("stream_consumer_processing_pending", extra={"stream": self.stream})
        while self._running:
            try:
                client = self._pool.async_client()
                try:
                    results = await client.xreadgroup(
                        groupname=self.group,
                        consumername=self.consumer_name,
                        streams={self.stream: "0"},  # "0" = pending messages
                        count=self._batch_size,
                    )
                finally:
                    await client.aclose()

                if not results:
                    break
                has_messages = False
                for _stream_name, messages in results:
                    if not messages:
                        continue
                    has_messages = True
                    for msg_id, fields in messages:
                        if not fields:
                            # Message was already acked or trimmed — just ack to clear
                            ack_client = self._pool.async_client()
                            try:
                                await ack_client.xack(self.stream, self.group, msg_id)
                            finally:
                                await ack_client.aclose()
                            continue
                        await self._handle_message(msg_id, fields)
                if not has_messages:
                    break

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("stream_consumer_pending_error", extra={"stream": self.stream})
                break

    async def _handle_message(self, msg_id: str, fields: dict[str, str]) -> None:
        """Call handler and ack on success."""
        start = time.monotonic()
        try:
            await self.handler(msg_id, fields)
            client = self._pool.async_client()
            try:
                await client.xack(self.stream, self.group, msg_id)
            finally:
                await client.aclose()
            self._messages_processed += 1
        except Exception:
            self._messages_failed += 1
            logger.exception(
                "stream_consumer_handler_error",
                extra={
                    "stream": self.stream,
                    "msg_id": msg_id,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                },
            )
            # Message stays in PEL (pending entries list) — will be retried on next restart
            # or can be picked up by XCLAIM from another consumer

    def get_stats(self) -> dict:
        """Return consumer stats for health monitoring."""
        return {
            "stream": self.stream,
            "group": self.group,
            "consumer": self.consumer_name,
            "running": self._running,
            "processed": self._messages_processed,
            "failed": self._messages_failed,
        }
```

- [ ] **Step 2: Verify consumer starts and stops cleanly**

```bash
cd backend && python -c "
import asyncio
from app.core.redis_pool import redis_pool
from app.core.stream_consumer import StreamConsumer

async def dummy_handler(msg_id, fields):
    print(f'Received: {msg_id} -> {fields}')

async def test():
    await redis_pool.start()
    consumer = StreamConsumer('test:stream', 'test-group', dummy_handler, redis_pool)
    await consumer.start()

    # Publish a test message
    msg_id = await redis_pool.stream_publish('test:stream', {'hello': 'world'})
    print(f'Published: {msg_id}')

    await asyncio.sleep(3)  # let consumer pick it up
    print(f'Stats: {consumer.get_stats()}')

    await consumer.stop()
    await redis_pool.stop()
    print('OK')

asyncio.run(test())
"
```

Expected: `Published: <id>`, `Received: <id> -> {'hello': 'world'}`, stats show `processed: 1`, then `OK`

- [ ] **Step 3: Clean up test stream**

```bash
cd backend && python -c "
import asyncio, redis.asyncio as r
async def cleanup():
    c = r.from_url('redis://localhost:6379/0')
    await c.delete('test:stream')
    await c.aclose()
    print('Cleaned up')
asyncio.run(cleanup())
"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/stream_consumer.py
git commit -m "feat: add generic Redis Stream consumer with consumer groups

Supports batch reads, configurable block timeout, crash recovery
via pending message reclaim, and per-message ack/nack."
```

---

## Task 3: Remove Dead Celery Code

**Files:**
- Delete: `backend/app/core/celery_app.py`
- Modify: `backend/app/modules/automation/workers/webhook_worker.py` (remove Celery task, keep `process_webhook` async function)
- Modify: `backend/app/modules/backup/workers.py` (remove Celery tasks, `queue_backup`, `schedule_periodic_backups`)
- Modify: `backend/requirements.txt` or `backend/pyproject.toml` (remove `celery`)

- [ ] **Step 1: Delete celery_app.py**

```bash
rm backend/app/core/celery_app.py
```

- [ ] **Step 2: Clean webhook_worker.py**

In `backend/app/modules/automation/workers/webhook_worker.py`:
- Remove the `from app.core.celery_app import celery_app` import
- Remove the entire `process_webhook_task` function (the `@celery_app.task` decorated function, lines 30-46)
- Keep the `async def process_webhook(...)` function (line 49+) completely unchanged

- [ ] **Step 3: Clean backup/workers.py**

In `backend/app/modules/backup/workers.py`:
- Remove `from app.core.celery_app import celery_app` import
- Remove `perform_backup_task` (the `@celery_app.task` function, lines 24-42)
- Remove `cleanup_old_backups_task` (lines 191-210)
- Remove `queue_backup()` function (lines 268-288)
- Remove `schedule_periodic_backups()` function (lines 290-310)
- Keep all async functions (`perform_backup`, `perform_full_backup`, `perform_incremental_backup`, `cleanup_old_backups`, etc.) unchanged

- [ ] **Step 4: Remove celery from dependencies**

In `backend/requirements.txt`: remove the line `celery>=5.4.0` (or equivalent).
If using `pyproject.toml`, remove `celery` from the dependencies list.

- [ ] **Step 5: Verify no remaining Celery imports**

```bash
cd backend && grep -rn "celery" app/ --include="*.py" | grep -v __pycache__
```

Expected: No results (or only comments/docs mentioning Celery historically).

- [ ] **Step 6: Verify the app still starts**

```bash
cd backend && python -c "from app.main import app; print('OK: app imports cleanly')"
```

- [ ] **Step 7: Commit**

```bash
git add -A backend/app/core/celery_app.py backend/app/modules/automation/workers/webhook_worker.py backend/app/modules/backup/workers.py backend/requirements.txt
git commit -m "chore: remove dead Celery code and dependency

Celery tasks were defined but never dispatched — all background work
already uses asyncio.create_task via create_background_task().
Removes celery_app.py, task decorators, queue_backup(),
schedule_periodic_backups(), and the celery pip dependency."
```

---

## Task 4: Wire Redis Pool into App Lifecycle

**Files:**
- Modify: `backend/app/main.py` (add redis_pool start/stop)
- Modify: `backend/app/api/v1/system_health.py` (use shared pool)

- [ ] **Step 1: Start/stop Redis pool in app lifespan**

In `backend/app/main.py`, inside the `lifespan` async context manager:

**Startup** — add after `Database.connect_db()` (before scheduler start):
```python
from app.core.redis_pool import redis_pool

# After Database.connect_db():
await redis_pool.start()
```

**Shutdown** — add before `Database.close_db()`:
```python
await redis_pool.stop()
```

- [ ] **Step 2: Update health check to use shared pool**

In `backend/app/api/v1/system_health.py`, replace the ad-hoc `_get_redis_client()` function:

```python
# REMOVE:
# def _get_redis_client():
#     import redis.asyncio as aioredis
#     return aioredis.from_url(settings.redis_url, decode_responses=True)

# REPLACE with:
from app.core.redis_pool import redis_pool
```

Update `_check_redis()` to use the pool:
```python
async def _check_redis() -> dict:
    try:
        if not redis_pool.is_started:
            return {"status": "unavailable", "error": "Redis pool not started"}
        client = redis_pool.async_client()
        try:
            await client.ping()
            info = await client.info(section="memory")
            clients_info = await client.info(section="clients")
            server_info = await client.info(section="server")
            # Stream stats
            streams = {}
            for stream_name in ["webhook:automation", "webhook:backup", "webhook:impact", "telemetry:ingestion"]:
                streams[stream_name] = await redis_pool.get_stream_info(stream_name)
            return {
                "status": "healthy",
                "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
                "connected_clients": clients_info.get("connected_clients", 0),
                "uptime_seconds": server_info.get("uptime_in_seconds", 0),
                "streams": streams,
            }
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning("redis_health_check_failed", error=str(e))
        return {"status": "unhealthy", "error": "connection failed"}
```

- [ ] **Step 3: Verify health endpoint works**

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 &
sleep 3
curl -s http://localhost:8000/api/v1/system/health | python -m json.tool | grep -A5 redis
kill %1
```

Expected: Redis status shows `"healthy"` with memory and stream info.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py backend/app/api/v1/system_health.py
git commit -m "feat: wire Redis pool into app lifecycle and health checks

Redis pool starts/stops with the app. Health endpoint uses the shared
pool and reports stream stats (length, pending, consumer lag)."
```

---

## Task 5: Webhook Consumers — Automation, Backup, Impact Analysis

**Files:**
- Modify: `backend/app/api/v1/webhooks.py` (publish to streams instead of `create_background_task`)
- Modify: `backend/app/modules/backup/webhook_handler.py` (return validated data instead of dispatching internally)
- Modify: `backend/app/main.py` (start/stop consumers)

This is the core task — replaces `create_background_task()` with Redis Stream publish/consume for all three webhook modules.

- [ ] **Step 1: Define stream names as constants**

Add to `backend/app/core/redis_pool.py` at the top (after imports):

```python
# Stream names — used by publishers and consumers
STREAM_WEBHOOK_AUTOMATION = "webhook:automation"
STREAM_WEBHOOK_BACKUP = "webhook:backup"
STREAM_WEBHOOK_IMPACT = "webhook:impact"
```

- [ ] **Step 2: Create handler functions for each consumer**

Add a new file `backend/app/core/webhook_consumers.py`:

```python
"""
Redis Stream consumer handlers for webhook event processing.

Each handler deserializes a Redis Stream message and calls the existing
async processing function. These are registered with StreamConsumer instances
in main.py startup.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


async def handle_automation_message(msg_id: str, fields: dict[str, str]) -> None:
    """Consumer handler for webhook:automation stream."""
    from app.modules.automation.workers.webhook_worker import process_webhook

    event_id = fields["event_id"]
    webhook_type = fields["webhook_type"]
    payload = json.loads(fields["payload"])
    event_type = fields.get("event_type") or None

    await process_webhook(event_id, webhook_type, payload, event_type=event_type)


async def handle_backup_message(msg_id: str, fields: dict[str, str]) -> None:
    """Consumer handler for webhook:backup stream."""
    from app.modules.backup.workers import perform_incremental_backup

    org_id = fields["org_id"]
    events = json.loads(fields["events"])

    await perform_incremental_backup(org_id, events)


async def handle_impact_message(msg_id: str, fields: dict[str, str]) -> None:
    """Consumer handler for webhook:impact stream."""
    from app.modules.impact_analysis.workers.event_handler import handle_device_event

    event_id = fields["event_id"]
    event_type = fields["event_type"]
    payload = json.loads(fields["payload"])

    await handle_device_event(event_id, event_type, payload)
```

- [ ] **Step 3: Modify the webhook gateway to publish to Redis Streams**

In `backend/app/api/v1/webhooks.py`, add imports:

```python
import json
from app.core.redis_pool import (
    redis_pool,
    STREAM_WEBHOOK_AUTOMATION,
    STREAM_WEBHOOK_BACKUP,
    STREAM_WEBHOOK_IMPACT,
)
```

Replace the three `create_background_task()` dispatch blocks in the per-event loop (inside `receive_mist_webhook`, around lines 233-248) with Redis Stream publishes:

**Automation dispatch** — replace `create_background_task(process_webhook(...))`:
```python
# Automation — publish to Redis Stream (with asyncio fallback)
try:
    if redis_pool.is_started:
        await redis_pool.stream_publish(
            STREAM_WEBHOOK_AUTOMATION,
            {
                "event_id": str(webhook_event.id),
                "webhook_type": webhook_type,
                "payload": json.dumps(enriched),
                "event_type": fields.get("event_type") or "",
            },
        )
    else:
        create_background_task(
            process_webhook(str(webhook_event.id), webhook_type, enriched, event_type=fields["event_type"]),
            name=f"webhook-automation-{evt_webhook_id}",
        )
except Exception:
    logger.exception("webhook_publish_failed", extra={"stream": "automation", "event_id": str(webhook_event.id)})
    # Fallback to direct asyncio dispatch
    create_background_task(
        process_webhook(str(webhook_event.id), webhook_type, enriched, event_type=fields["event_type"]),
        name=f"webhook-automation-{evt_webhook_id}",
    )
```

**Impact analysis dispatch** — replace `create_background_task(handle_device_event(...))`:
```python
if webhook_type == "device-events":
    try:
        if redis_pool.is_started:
            await redis_pool.stream_publish(
                STREAM_WEBHOOK_IMPACT,
                {
                    "event_id": str(webhook_event.id),
                    "event_type": fields.get("event_type") or "",
                    "payload": json.dumps(enriched),
                },
            )
        else:
            create_background_task(
                handle_device_event(str(webhook_event.id), fields["event_type"], enriched),
                name=f"impact-{evt_webhook_id}",
            )
    except Exception:
        logger.exception("webhook_publish_failed", extra={"stream": "impact", "event_id": str(webhook_event.id)})
        create_background_task(
            handle_device_event(str(webhook_event.id), fields["event_type"], enriched),
            name=f"impact-{evt_webhook_id}",
        )
```

- [ ] **Step 4: Modify backup webhook handler**

In `backend/app/modules/backup/webhook_handler.py`, modify `process_backup_webhook` to publish to Redis instead of calling `create_background_task(perform_incremental_backup(...))` internally.

Replace the `create_background_task(perform_incremental_backup(...))` call (around line 55-60) with:

```python
# Publish to Redis Stream (with asyncio fallback)
try:
    from app.core.redis_pool import redis_pool, STREAM_WEBHOOK_BACKUP

    if redis_pool.is_started:
        await redis_pool.stream_publish(
            STREAM_WEBHOOK_BACKUP,
            {
                "org_id": configured_org_id,
                "events": json.dumps(events),
            },
        )
    else:
        create_background_task(
            perform_incremental_backup(configured_org_id, events),
            name=f"backup-incremental-{len(events)}-events",
        )
except Exception:
    logger.exception("backup_publish_failed")
    create_background_task(
        perform_incremental_backup(configured_org_id, events),
        name=f"backup-incremental-{len(events)}-events",
    )
```

Add `import json` at the top if not already present.

- [ ] **Step 5: Modify the replay endpoint**

In `backend/app/api/v1/webhooks.py`, in `replay_webhook_event` (around line 430), replace:
```python
create_background_task(process_webhook(...))
```
with:
```python
try:
    if redis_pool.is_started:
        await redis_pool.stream_publish(
            STREAM_WEBHOOK_AUTOMATION,
            {
                "event_id": str(event.id),
                "webhook_type": event.webhook_type,
                "payload": json.dumps(event.payload),
                "event_type": event.event_type or "",
            },
        )
    else:
        create_background_task(
            process_webhook(str(event.id), event.webhook_type, event.payload, event_type=event.event_type),
            name=f"replay-{event_id}",
        )
except Exception:
    logger.exception("replay_publish_failed", extra={"event_id": event_id})
    create_background_task(
        process_webhook(str(event.id), event.webhook_type, event.payload, event_type=event.event_type),
        name=f"replay-{event_id}",
    )
```

- [ ] **Step 6: Start webhook consumers in app lifespan**

In `backend/app/main.py`, add to startup (after `redis_pool.start()`, before scheduler):

```python
from app.core.stream_consumer import StreamConsumer
from app.core.redis_pool import STREAM_WEBHOOK_AUTOMATION, STREAM_WEBHOOK_BACKUP, STREAM_WEBHOOK_IMPACT
from app.core.webhook_consumers import handle_automation_message, handle_backup_message, handle_impact_message

# Start webhook stream consumers
_webhook_consumers: list[StreamConsumer] = []

# Inside lifespan startup:
automation_consumer = StreamConsumer(
    STREAM_WEBHOOK_AUTOMATION, "automation-workers", handle_automation_message, redis_pool
)
backup_consumer = StreamConsumer(
    STREAM_WEBHOOK_BACKUP, "backup-workers", handle_backup_message, redis_pool
)
impact_consumer = StreamConsumer(
    STREAM_WEBHOOK_IMPACT, "impact-workers", handle_impact_message, redis_pool
)
for consumer in [automation_consumer, backup_consumer, impact_consumer]:
    await consumer.start()
    _webhook_consumers.append(consumer)
```

In shutdown (before `redis_pool.stop()`):
```python
for consumer in _webhook_consumers:
    await consumer.stop()
```

- [ ] **Step 7: Integration test — send a test webhook and verify stream processing**

```bash
# Start the app, then send a test webhook
cd backend && uvicorn app.main:app --port 8000 &
sleep 3

# Check streams exist
python -c "
import asyncio, redis.asyncio as r
async def check():
    c = r.from_url('redis://localhost:6379/0')
    for s in ['webhook:automation', 'webhook:backup', 'webhook:impact']:
        try:
            info = await c.xinfo_stream(s)
            print(f'{s}: length={info[\"length\"]}')
        except:
            print(f'{s}: not yet created (OK — created on first message)')
    await c.aclose()
asyncio.run(check())
"

kill %1
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/redis_pool.py backend/app/core/webhook_consumers.py backend/app/api/v1/webhooks.py backend/app/modules/backup/webhook_handler.py backend/app/main.py
git commit -m "feat: webhook ingestion via Redis Streams

Gateway publishes events to per-module Redis Streams instead of
create_background_task(). Three consumer loops (automation, backup,
impact) read from streams and call existing processing functions.
Graceful fallback to asyncio dispatch if Redis is unavailable."
```

---

## Task 6: Telemetry WS Ingestion via Redis Stream

**Files:**
- Modify: `backend/app/modules/telemetry/services/mist_ws_manager.py` (replace asyncio.Queue with Redis XADD)
- Modify: `backend/app/modules/telemetry/services/ingestion_service.py` (replace asyncio.Queue consumer with Redis Stream consumer)
- Modify: `backend/app/modules/telemetry/services/lifecycle.py` (wire Redis pool, remove queue passing)

- [ ] **Step 1: Add telemetry stream constant**

In `backend/app/core/redis_pool.py`, add:

```python
STREAM_TELEMETRY_INGESTION = "telemetry:ingestion"
```

- [ ] **Step 2: Modify MistWsManager to publish to Redis**

In `backend/app/modules/telemetry/services/mist_ws_manager.py`:

Replace the `asyncio.Queue` + `call_soon_threadsafe` pattern with a sync Redis `XADD`.

**Constructor changes** — replace `message_queue: asyncio.Queue` parameter with `redis_pool: RedisPool`:
```python
from app.core.redis_pool import RedisPool, STREAM_TELEMETRY_INGESTION

def __init__(self, api_session, redis_pool: RedisPool):
    self._api_session = api_session
    self._redis = redis_pool.sync_client()  # thread-safe sync client
    self._connections: list = []
    self._messages_received = 0
    self._messages_publish_failed = 0
    # Remove: self._message_queue, self._loop, self._messages_bridge_dropped
```

**Replace `_on_ws_message`** — remove `call_soon_threadsafe` + `_safe_enqueue`, use direct Redis XADD:
```python
def _on_ws_message(self, msg: dict) -> None:
    """WS callback — runs in background thread. Publishes to Redis Stream."""
    self._messages_received += 1
    try:
        # msg["data"] is already a JSON string from Mist — pass through without re-serialization
        data_str = msg.get("data", "")
        if isinstance(data_str, dict):
            import json
            data_str = json.dumps(data_str)
        self._redis.xadd(
            STREAM_TELEMETRY_INGESTION,
            {
                "channel": msg.get("channel", ""),
                "event": msg.get("event", ""),
                "data": data_str,
            },
            maxlen=settings.redis_stream_max_len,
            approximate=True,
        )
    except Exception:
        self._messages_publish_failed += 1
        # Don't log every failure at scale — would flood logs
        if self._messages_publish_failed % 1000 == 1:
            logger.warning(
                "telemetry_ws_publish_failed",
                extra={"total_failed": self._messages_publish_failed},
            )
```

**Remove `_safe_enqueue`** — no longer needed.

**Remove `start()` event loop capture** — `self._loop = asyncio.get_running_loop()` is no longer needed.

**Update `get_status()`** — replace `_messages_bridge_dropped` with `_messages_publish_failed`.

- [ ] **Step 3: Modify IngestionService to consume from Redis Stream**

In `backend/app/modules/telemetry/services/ingestion_service.py`:

**Constructor changes** — remove `asyncio.Queue` creation, accept `redis_pool` instead:
```python
from app.core.redis_pool import RedisPool, STREAM_TELEMETRY_INGESTION
from app.core.stream_consumer import StreamConsumer

def __init__(self, influxdb_service, cov_filter, cache, org_id, redis_pool: RedisPool):
    # ... existing fields ...
    self._redis_pool = redis_pool
    self._consumer: StreamConsumer | None = None
    # Remove: self._queue = asyncio.Queue(maxsize=10_000)
```

**Remove `get_queue()`** — no longer needed.

**Replace `start()`**:
```python
async def start(self) -> None:
    self._running = True
    self._consumer = StreamConsumer(
        stream=STREAM_TELEMETRY_INGESTION,
        group="telemetry-ingestion",
        handler=self._handle_stream_message,
        pool=self._redis_pool,
        batch_size=100,  # telemetry is high-volume, read in bigger batches
        block_ms=1000,
    )
    await self._consumer.start()
```

**Add stream message handler** (bridges Redis fields → existing `_process_message`):
```python
async def _handle_stream_message(self, msg_id: str, fields: dict[str, str]) -> None:
    """Adapter: Redis Stream message → existing _process_message."""
    msg = {
        "event": fields.get("event", ""),
        "channel": fields.get("channel", ""),
        "data": fields.get("data", ""),
    }
    await self._process_message(msg)
```

**Remove `_consume_loop()`** — replaced by `StreamConsumer._consume_loop`.

**Replace `stop()`**:
```python
async def stop(self) -> None:
    self._running = False
    if self._consumer:
        await self._consumer.stop()
```

- [ ] **Step 4: Update lifecycle.py wiring**

In `backend/app/modules/telemetry/services/lifecycle.py`:

Replace queue-based wiring with Redis pool:
```python
from app.core.redis_pool import redis_pool

# In start_telemetry_pipeline():
# BEFORE:
#   ingestion = IngestionService(influxdb, cov, cache, org_id)
#   ws_manager = MistWsManager(api_session, ingestion.get_queue())
# AFTER:
ingestion = IngestionService(influxdb, cov, cache, org_id, redis_pool)
ws_manager = MistWsManager(api_session, redis_pool)
```

- [ ] **Step 5: Verify telemetry pipeline starts**

```bash
cd backend && python -c "
from app.core.redis_pool import redis_pool
import asyncio
async def test():
    await redis_pool.start()
    # Just verify the imports and construction work
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.mist_ws_manager import MistWsManager
    print('OK: imports clean, no circular deps')
    await redis_pool.stop()
asyncio.run(test())
"
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/redis_pool.py backend/app/modules/telemetry/services/mist_ws_manager.py backend/app/modules/telemetry/services/ingestion_service.py backend/app/modules/telemetry/services/lifecycle.py
git commit -m "feat: telemetry WS ingestion via Redis Stream

Replace asyncio.Queue + call_soon_threadsafe bridge with Redis Stream.
WS thread publishes via sync Redis client (thread-safe, no event loop
dependency). IngestionService consumes via StreamConsumer. Eliminates
silent message drops on queue full — Redis absorbs bursts."
```

---

## Task 7: APScheduler Redis Job Store

**Files:**
- Modify: `backend/app/modules/automation/workers/scheduler.py` (replace MemoryJobStore with RedisJobStore)

- [ ] **Step 1: Install apscheduler Redis dependency**

APScheduler 3.x `RedisJobStore` uses the sync `redis` client (already installed).

Verify it's available:
```bash
cd backend && python -c "from apscheduler.jobstores.redis import RedisJobStore; print('OK')"
```

If not found, check APScheduler version — `RedisJobStore` is available in `apscheduler>=3.2.0`.

- [ ] **Step 2: Replace MemoryJobStore with RedisJobStore**

In `backend/app/modules/automation/workers/scheduler.py`, replace the job store configuration:

```python
# BEFORE (around line 28-30):
# from apscheduler.jobstores.memory import MemoryJobStore
# jobstores = {"default": MemoryJobStore()}

# AFTER:
from apscheduler.jobstores.redis import RedisJobStore
from app.config import settings

jobstores = {"default": RedisJobStore(url=settings.redis_url)}
```

Keep everything else unchanged — `AsyncIOExecutor`, `AsyncIOScheduler`, job defaults (`coalesce`, `max_instances`, `misfire_grace_time`).

**Important:** With `RedisJobStore`, jobs persist across restarts. The startup code that loads jobs from MongoDB (`_load_cron_workflows`, `_load_backup_schedule`) already uses `replace_existing=True`, so it will update existing Redis-stored jobs rather than creating duplicates. No changes needed there.

- [ ] **Step 3: Verify scheduler starts with Redis job store**

```bash
cd backend && python -c "
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

scheduler = AsyncIOScheduler(
    jobstores={'default': RedisJobStore(url='redis://localhost:6379/0')},
    executors={'default': AsyncIOExecutor()},
    job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 300},
)
scheduler.start()
print(f'OK: scheduler running, jobs: {scheduler.get_jobs()}')
scheduler.shutdown()
"
```

Expected: `OK: scheduler running, jobs: [...]`

- [ ] **Step 4: Commit**

```bash
git add backend/app/modules/automation/workers/scheduler.py
git commit -m "feat: APScheduler RedisJobStore for crash-resilient scheduling

Replace MemoryJobStore with RedisJobStore so scheduled jobs survive
process restarts without depending on misfire_grace_time catch-up."
```

---

## Task 8: Update CLAUDE.md Documentation

**Files:**
- Modify: `CLAUDE.md` (root)
- Modify: `backend/CLAUDE.md`
- Modify: `backend/app/modules/telemetry/CLAUDE.md`

- [ ] **Step 1: Update root CLAUDE.md**

In the Architecture section, update the "Prerequisites" paragraph to mention Redis is now actively used:
```
**Prerequisites**: MongoDB on localhost:27017, Redis on localhost:6379 (required — used as ingestion buffer via Redis Streams and APScheduler job store), InfluxDB 2.7 on localhost:8086 (optional, for telemetry).
```

Add a new subsection after "Webhook Event Routing" explaining the Redis ingestion pipeline:

```markdown
### Redis Ingestion Pipeline

**Purpose**: Decouples data ingestion from processing for burst absorption, crash resilience, and future horizontal scaling.

**Streams**:
| Stream | Producer | Consumer Group | Handler |
|--------|----------|---------------|---------|
| `webhook:automation` | Webhook gateway | `automation-workers` | `process_webhook()` |
| `webhook:backup` | Webhook gateway (audits only) | `backup-workers` | `perform_incremental_backup()` |
| `webhook:impact` | Webhook gateway (device-events only) | `impact-workers` | `handle_device_event()` |
| `telemetry:ingestion` | MistWsManager (sync client from WS thread) | `telemetry-ingestion` | `IngestionService._process_message()` |

**Key files**:
- `app/core/redis_pool.py` — Shared async + sync connection pools, stream publish helper, stream info for health checks
- `app/core/stream_consumer.py` — Generic `StreamConsumer` class (XREADGROUP, handler dispatch, XACK, pending message recovery)
- `app/core/webhook_consumers.py` — Handler functions that deserialize Redis fields and call existing processing functions

**Patterns**:
- Graceful fallback: if Redis is down, webhook gateway falls back to `create_background_task()` (asyncio)
- Crash recovery: `StreamConsumer` reclaims pending (delivered but unacked) messages on startup
- Stream capping: `MAXLEN ~100000` (approximate) prevents unbounded growth
- Consumer groups: designed for single consumer now, add workers by starting another process with the same group name
```

- [ ] **Step 2: Update backend/CLAUDE.md and telemetry/CLAUDE.md**

Add the Redis pool pattern to backend CLAUDE.md patterns section:
```markdown
- **Redis pool**: Always use `redis_pool.async_client()` (async) or `redis_pool.sync_client()` (threads) — never create ad-hoc `aioredis.from_url()` connections. Publish to streams via `redis_pool.stream_publish()`.
```

Update telemetry CLAUDE.md to reflect the Redis-based ingestion:
```markdown
**Ingestion**: MistWsManager publishes raw WS messages to Redis Stream `telemetry:ingestion` via sync client (thread-safe). IngestionService consumes via `StreamConsumer`. The asyncio.Queue bridge is replaced.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md backend/CLAUDE.md backend/app/modules/telemetry/CLAUDE.md
git commit -m "docs: update CLAUDE.md files for Redis ingestion pipeline"
```

---

## Task 9: Cleanup and Final Verification

- [ ] **Step 1: Verify no stale imports**

```bash
cd backend && python -c "
import ast, sys, pathlib

stale = ['celery', 'celery_app']
found = []
for p in pathlib.Path('app').rglob('*.py'):
    tree = ast.parse(p.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            src = ast.dump(node)
            for s in stale:
                if s in src:
                    found.append(f'{p}:{node.lineno}: {ast.get_source_segment(p.read_text(), node)}')
if found:
    print('STALE IMPORTS FOUND:')
    for f in found:
        print(f'  {f}')
    sys.exit(1)
else:
    print('OK: no stale Celery imports')
"
```

- [ ] **Step 2: Run existing tests**

```bash
cd backend && python -m pytest tests/ -x -q 2>&1 | tail -20
```

Fix any failures caused by the refactor (most likely import-related in test mocks).

- [ ] **Step 3: Verify full app startup with all consumers**

```bash
cd backend && timeout 10 uvicorn app.main:app --port 8000 2>&1 | grep -E "redis|consumer|stream|scheduler"
```

Expected output should show:
- `redis_pool_started`
- `stream_consumer_started` (×4: automation, backup, impact, telemetry)
- Scheduler start with RedisJobStore

- [ ] **Step 4: Verify docker-compose still works**

```bash
docker-compose up -d redis
docker-compose logs redis | tail -5
```

Confirm Redis starts cleanly.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: cleanup stale imports and verify Redis pipeline integration"
```

---

## Summary of Changes

| What | Before | After |
|------|--------|-------|
| Webhook dispatch | `create_background_task()` (asyncio, fire-and-forget) | Redis Stream publish → consumer → existing handler |
| Telemetry WS bridge | `call_soon_threadsafe` → `asyncio.Queue(10K)` → `put_nowait` (drops) | Sync Redis `XADD` (thread-safe) → `StreamConsumer` |
| Crash resilience | None — in-flight tasks lost on restart | Redis Streams persist; pending messages reclaimed on startup |
| Burst absorption | Event loop saturated | Redis absorbs millions of ops/sec; consumers drain at their own pace |
| Horizontal scaling | Not possible | Add workers to same consumer group (zero code changes) |
| Scheduled jobs | `MemoryJobStore` — lost on restart, rebuilt from MongoDB | `RedisJobStore` — persist across restarts |
| Celery | Dead code (installed, never used) | Removed |
| Redis health | Ad-hoc client per check | Shared pool + stream stats (length, pending, lag) |

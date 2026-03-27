# Telemetry WebSocket + Ingestion Implementation Plan (Plan 3 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the Mist WebSocket stream to the telemetry pipeline -- ingest raw payloads, extract metrics, apply CoV filtering, write to InfluxDB, and update the in-memory cache.

**Architecture:** `MistWsManager` manages thread-based `mistapi.websockets` connections, bridges messages to asyncio via `loop.call_soon_threadsafe()`. `IngestionService` consumes from the queue, dispatches to extractors, applies CoV filtering, and writes to InfluxDB + cache.

**Tech Stack:** Python 3.10+, mistapi.websockets, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-websocket-telemetry-pipeline-design.md`

**Depends on:** Plan 1 (foundation) + Plan 2 (extractors) -- already implemented.

---

# Plan: Telemetry WebSocket + Ingestion (Plan 3)

```
# 2026-03-26-telemetry-ws-ingestion.md
#
# Spec: docs/superpowers/specs/2026-03-26-websocket-telemetry-pipeline-design.md
# Scope: MistWsManager (WebSocket lifecycle, auto-scaling, thread-to-asyncio bridge)
#         and IngestionService (queue consumer, extractor dispatch, CoV filtering,
#         InfluxDB writes, cache updates). Plus lifespan integration and router enhancements.
#
# NOTE FOR AGENTIC WORKER:
# Each step below is fully self-contained. Execute them IN ORDER.
# Every step includes exact file paths, complete code, and the shell commands to run.
# Do NOT skip steps. Do NOT combine steps. Commit after each green test.
# Working directory for all commands: cd /Users/tmunzer/4_dev/mist_automation/backend
```

---

## Step 1 -- IngestionService: write failing tests

- [ ] Create test file

**Create file:** `backend/tests/unit/test_ingestion_service.py`

```python
"""Unit tests for the IngestionService."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.telemetry.services.cov_filter import CoVFilter
from app.modules.telemetry.services.influxdb_service import InfluxDBService
from app.modules.telemetry.services.latest_value_cache import LatestValueCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_influxdb_mock() -> InfluxDBService:
    """Create a mock InfluxDBService with an async write_points."""
    svc = MagicMock(spec=InfluxDBService)
    svc.write_points = AsyncMock()
    return svc


def _make_ws_message(site_id: str, payload: dict) -> dict:
    """Build a WebSocket message dict matching Mist format."""
    return {
        "event": "data",
        "channel": f"/sites/{site_id}/stats/devices",
        "data": json.dumps(payload),
    }


def _ap_payload(mac: str = "aabbccddeeff") -> dict:
    """Minimal full-stats AP payload (has model + radio_stat)."""
    return {
        "mac": mac,
        "name": "AP-Test",
        "model": "AP45",
        "type": "ap",
        "cpu_util": 42,
        "mem_total_kb": 1048576,
        "mem_used_kb": 524288,
        "num_clients": 5,
        "uptime": 3600,
        "last_seen": 1774576960,
        "radio_stat": {
            "band_5": {
                "channel": 36,
                "power": 20,
                "bandwidth": 80,
                "util_all": 30,
                "noise_floor": -95,
                "num_clients": 5,
            },
        },
    }


def _basic_ap_payload(mac: str = "aabbccddeeff") -> dict:
    """Basic AP payload (no model) -- should be skipped by extractors."""
    return {
        "mac": mac,
        "uptime": 3600,
        "ip_stat": {"ip": "10.0.0.1"},
        "last_seen": 1774576960,
    }


def _switch_payload(mac: str = "112233445566") -> dict:
    """Minimal switch payload."""
    return {
        "mac": mac,
        "name": "SW-Core-01",
        "type": "switch",
        "cpu_stat": {"idle": 80},
        "memory_stat": {"usage": 45},
        "uptime": 7200,
        "last_seen": 1774576960,
        "module_stat": [],
    }


# ---------------------------------------------------------------------------
# Tests: construction
# ---------------------------------------------------------------------------


class TestIngestionServiceInit:
    """Test IngestionService construction."""

    def test_creates_with_dependencies(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        assert svc._running is False
        assert svc._messages_processed == 0
        assert svc._messages_dropped == 0

    def test_get_queue_returns_bounded_queue(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        q = svc.get_queue()
        assert isinstance(q, asyncio.Queue)
        assert q.maxsize == 10_000

    def test_custom_queue_size(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
            queue_maxsize=100,
        )
        assert svc.get_queue().maxsize == 100


# ---------------------------------------------------------------------------
# Tests: message processing
# ---------------------------------------------------------------------------


class TestIngestionServiceProcessMessage:
    """Test _process_message logic."""

    @pytest.mark.asyncio
    async def test_processes_ap_message_updates_cache(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        cache = LatestValueCache()
        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=cache,
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)

        # Cache should have the device
        cached = cache.get("aabbccddeeff")
        assert cached is not None
        assert cached["mac"] == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_processes_ap_message_writes_to_influxdb(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)

        # InfluxDB should receive at least device_summary + radio_stats
        assert influxdb.write_points.called
        points = influxdb.write_points.call_args[0][0]
        measurements = [p["measurement"] for p in points]
        assert "device_summary" in measurements

    @pytest.mark.asyncio
    async def test_processes_ap_message_increments_counter(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)
        assert svc._messages_processed == 1

    @pytest.mark.asyncio
    async def test_skips_basic_ap_messages(self):
        """Basic AP payloads (no model) produce zero extractor points -- nothing written."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        cache = LatestValueCache()
        svc = IngestionService(
            influxdb=influxdb,
            cache=cache,
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _basic_ap_payload())
        await svc._process_message(msg)

        # Cache still updated (full payload stored for latest state)
        cached = cache.get("aabbccddeeff")
        assert cached is not None

        # But no points to write to InfluxDB
        if influxdb.write_points.called:
            points = influxdb.write_points.call_args[0][0]
            assert len(points) == 0

    @pytest.mark.asyncio
    async def test_extracts_site_id_from_channel(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("978c48e6-6ef6-11e6-8bbf-02e208b2d34f", _ap_payload())
        await svc._process_message(msg)

        points = influxdb.write_points.call_args[0][0]
        summary = next(p for p in points if p["measurement"] == "device_summary")
        assert summary["tags"]["site_id"] == "978c48e6-6ef6-11e6-8bbf-02e208b2d34f"

    @pytest.mark.asyncio
    async def test_non_data_event_is_ignored(self):
        """Messages with event != 'data' should be ignored."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = {"event": "subscribe_ok", "channel": "/sites/s1/stats/devices"}
        await svc._process_message(msg)
        assert svc._messages_processed == 0

    @pytest.mark.asyncio
    async def test_malformed_json_data_is_handled(self):
        """data field with invalid JSON should not crash."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = {
            "event": "data",
            "channel": "/sites/s1/stats/devices",
            "data": "not valid json{{{",
        }
        await svc._process_message(msg)
        # Should not crash, message counter stays at 0
        assert svc._messages_processed == 0


# ---------------------------------------------------------------------------
# Tests: CoV filtering integration
# ---------------------------------------------------------------------------


class TestIngestionServiceCoVFiltering:
    """Test that CoV filtering is applied to non-summary measurements."""

    @pytest.mark.asyncio
    async def test_device_summary_always_written(self):
        """device_summary points should always be written (no CoV)."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        # Process the same message twice
        await svc._process_message(msg)
        await svc._process_message(msg)

        # Both calls should include device_summary
        assert influxdb.write_points.call_count == 2
        for call in influxdb.write_points.call_args_list:
            points = call[0][0]
            summaries = [p for p in points if p["measurement"] == "device_summary"]
            assert len(summaries) == 1

    @pytest.mark.asyncio
    async def test_radio_stats_filtered_on_no_change(self):
        """Identical radio_stats should be filtered out on second write (CoV)."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())

        # First write: all points pass
        await svc._process_message(msg)
        first_points = influxdb.write_points.call_args[0][0]
        first_radios = [p for p in first_points if p["measurement"] == "radio_stats"]
        assert len(first_radios) == 1  # band_5

        # Second write: radio_stats should be filtered (no change)
        await svc._process_message(msg)
        second_points = influxdb.write_points.call_args[0][0]
        second_radios = [p for p in second_points if p["measurement"] == "radio_stats"]
        assert len(second_radios) == 0

    @pytest.mark.asyncio
    async def test_radio_stats_passes_on_significant_change(self):
        """radio_stats should pass CoV when value changes beyond threshold."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )

        # First message
        payload1 = _ap_payload()
        await svc._process_message(_make_ws_message("site-1", payload1))

        # Second message with significant util_all change (>5.0 threshold)
        payload2 = _ap_payload()
        payload2["radio_stat"]["band_5"]["util_all"] = 50  # was 30, delta = 20
        await svc._process_message(_make_ws_message("site-1", payload2))

        second_points = influxdb.write_points.call_args[0][0]
        second_radios = [p for p in second_points if p["measurement"] == "radio_stats"]
        assert len(second_radios) == 1

    @pytest.mark.asyncio
    async def test_gateway_health_always_written(self):
        """gateway_health points should always be written (like device_summary)."""
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        gw_payload = {
            "mac": "aabb11223344",
            "type": "gateway",
            "model": "SRX300",
            "cpu_stat": {"idle": 90},
            "memory_stat": {"usage": 30},
            "uptime": 99999,
            "last_seen": 1774576960,
        }
        msg = _make_ws_message("site-1", gw_payload)
        await svc._process_message(msg)
        await svc._process_message(msg)

        # Both should have gateway_health
        for call in influxdb.write_points.call_args_list:
            points = call[0][0]
            healths = [p for p in points if p["measurement"] == "gateway_health"]
            assert len(healths) == 1


# ---------------------------------------------------------------------------
# Tests: get_stats
# ---------------------------------------------------------------------------


class TestIngestionServiceStats:
    """Test get_stats returns expected metrics."""

    @pytest.mark.asyncio
    async def test_stats_after_processing(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        msg = _make_ws_message("site-1", _ap_payload())
        await svc._process_message(msg)

        stats = svc.get_stats()
        assert stats["messages_processed"] == 1
        assert stats["messages_dropped"] == 0
        assert "queue_size" in stats
        assert "queue_capacity" in stats
        assert stats["running"] is False


# ---------------------------------------------------------------------------
# Tests: start / stop lifecycle
# ---------------------------------------------------------------------------


class TestIngestionServiceLifecycle:
    """Test start and stop manage the consumer task."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        await svc.start()
        assert svc._running is True
        assert svc._task is not None
        await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        svc = IngestionService(
            influxdb=_make_influxdb_mock(),
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        await svc.start()
        task = svc._task
        await svc.stop()
        assert svc._running is False
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_consume_loop_processes_queued_messages(self):
        from app.modules.telemetry.services.ingestion_service import IngestionService

        influxdb = _make_influxdb_mock()
        svc = IngestionService(
            influxdb=influxdb,
            cache=LatestValueCache(),
            cov_filter=CoVFilter(),
            org_id="org-1",
        )
        await svc.start()

        # Put a message into the queue
        msg = _make_ws_message("site-1", _ap_payload())
        await svc.get_queue().put(msg)

        # Allow the consume loop to pick it up
        await asyncio.sleep(0.1)

        assert svc._messages_processed == 1
        assert influxdb.write_points.called

        await svc.stop()
```

### 1b. Run tests -- expect failures (module not found)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_ingestion_service.py -x -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.modules.telemetry.services.ingestion_service'`

### 1c. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add tests/unit/test_ingestion_service.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add failing tests for IngestionService

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 2 -- IngestionService: implement to pass all tests

- [ ] Create ingestion service

**Create file:** `backend/app/modules/telemetry/services/ingestion_service.py`

```python
"""Ingestion service — consumes WebSocket messages, extracts metrics, applies CoV, writes to InfluxDB + cache.

Bridges the gap between the MistWsManager (which puts raw WS messages into an
asyncio.Queue) and the storage layer (InfluxDB + LatestValueCache). Each message
is parsed, dispatched to the appropriate device-type extractor, CoV-filtered,
and then written.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import structlog

from app.modules.telemetry.extractors import extract_points
from app.modules.telemetry.services.cov_filter import CoVFilter
from app.modules.telemetry.services.influxdb_service import InfluxDBService
from app.modules.telemetry.services.latest_value_cache import LatestValueCache

logger = structlog.get_logger(__name__)

# Regex to extract site_id from channel string: /sites/{uuid}/stats/devices
_CHANNEL_SITE_RE = re.compile(r"/sites/([^/]+)/stats/devices")

# Measurements that bypass CoV filtering (always written every cycle)
_ALWAYS_WRITE_MEASUREMENTS = frozenset({"device_summary", "gateway_health"})

# Per-measurement CoV thresholds.  Keys are field names, values are:
# - "exact": write when value differs
# - "always": always write (monotonic counters)
# - float: write when absolute delta exceeds threshold
COV_THRESHOLDS: dict[str, dict[str, str | float]] = {
    "radio_stats": {
        "channel": "exact",
        "power": "exact",
        "bandwidth": "exact",
        "util_all": 5.0,
        "noise_floor": 3.0,
        "num_clients": "exact",
    },
    "port_stats": {
        "up": "exact",
        "tx_pkts": "always",
        "rx_pkts": "always",
        "speed": "exact",
    },
    "module_stats": {
        "temp_max": 2.0,
        "poe_draw": 5.0,
        "vc_role": "exact",
        "vc_links_count": "exact",
        "mem_usage": 5.0,
    },
    "gateway_wan": {
        "up": "exact",
        "tx_bytes": "always",
        "rx_bytes": "always",
        "tx_pkts": "always",
        "rx_pkts": "always",
        "redundancy_state": "exact",
    },
    "gateway_spu": {
        "spu_cpu": 5.0,
        "spu_sessions": "always",
        "spu_max_sessions": "exact",
        "spu_memory": 5.0,
    },
    "gateway_resources": {
        "count": "always",
        "limit": "exact",
        "utilization_pct": 3.0,
    },
    "gateway_cluster": {
        "status": "exact",
        "operational": "exact",
        "primary_health": "exact",
        "secondary_health": "exact",
        "control_link_up": "exact",
        "fabric_link_up": "exact",
    },
    "gateway_dhcp": {
        "num_ips": "exact",
        "num_leased": "exact",
        "utilization_pct": 3.0,
    },
}


def _build_cov_key(point: dict[str, Any]) -> str:
    """Build a unique CoV key from a data point's measurement + identity tags.

    Key format: ``mac:measurement:tag_subset`` where tag_subset includes
    distinguishing tags (band, port_id, fpc_idx, etc.) but excludes
    org_id, site_id, name, device_type, model, router_name.
    """
    tags = point.get("tags", {})
    mac = tags.get("mac", "")
    measurement = point.get("measurement", "")

    # Collect distinguishing sub-tags (order-stable because dicts are ordered in 3.7+)
    skip_tags = {"org_id", "site_id", "mac", "name", "device_type", "model", "router_name", "node_name"}
    sub_parts = []
    for k, v in sorted(tags.items()):
        if k not in skip_tags and v != "":
            sub_parts.append(f"{k}={v}")
    tag_suffix = ",".join(sub_parts) if sub_parts else ""

    return f"{mac}:{measurement}:{tag_suffix}"


class IngestionService:
    """Consumes WS messages from a queue, extracts metrics, and writes to InfluxDB + cache."""

    def __init__(
        self,
        influxdb: InfluxDBService,
        cache: LatestValueCache,
        cov_filter: CoVFilter,
        org_id: str,
        queue_maxsize: int = 10_000,
    ) -> None:
        self._influxdb = influxdb
        self._cache = cache
        self._cov = cov_filter
        self._org_id = org_id
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = False
        self._task: asyncio.Task | None = None

        # Stats
        self._messages_processed = 0
        self._messages_dropped = 0
        self._points_extracted = 0
        self._points_written = 0
        self._points_filtered = 0
        self._last_message_at: float = 0

    def get_queue(self) -> asyncio.Queue[dict[str, Any]]:
        """Return the queue for the WS manager to post messages into."""
        return self._queue

    async def start(self) -> None:
        """Start the consumer coroutine."""
        self._running = True
        self._task = asyncio.create_task(self._consume_loop(), name="ingestion_consumer")
        logger.info("ingestion_service_started")

    async def stop(self) -> None:
        """Stop consuming and cancel the task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(
            "ingestion_service_stopped",
            messages_processed=self._messages_processed,
            points_written=self._points_written,
        )

    async def _consume_loop(self) -> None:
        """Main loop: dequeue -> parse -> extract -> CoV filter -> cache + write."""
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._process_message(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("ingestion_consume_error", error=str(e))

    async def _process_message(self, msg: dict[str, Any]) -> None:
        """Process a single WebSocket message through the full pipeline."""
        # 1. Only process "data" events
        if msg.get("event") != "data":
            return

        # 2. Extract site_id from channel
        channel = msg.get("channel", "")
        match = _CHANNEL_SITE_RE.search(channel)
        if not match:
            logger.debug("ingestion_unknown_channel", channel=channel)
            return
        site_id = match.group(1)

        # 3. Parse the data JSON string
        raw_data = msg.get("data")
        if not raw_data:
            return
        try:
            if isinstance(raw_data, str):
                payload = json.loads(raw_data)
            else:
                payload = raw_data
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("ingestion_json_parse_error", error=str(e))
            return

        if not isinstance(payload, dict):
            return

        # 4. Update LatestValueCache with the full payload
        mac = payload.get("mac", "")
        if mac:
            self._cache.update(mac, payload)

        # 5. Extract InfluxDB data points
        points = extract_points(payload, self._org_id, site_id)
        self._points_extracted += len(points)

        if not points:
            # Still count as processed (e.g., basic AP messages update cache but yield no points)
            self._messages_processed += 1
            self._last_message_at = time.time()
            return

        # 6. Apply CoV filtering
        filtered_points: list[dict[str, Any]] = []
        for point in points:
            measurement = point.get("measurement", "")

            if measurement in _ALWAYS_WRITE_MEASUREMENTS:
                # Always write device_summary and gateway_health
                filtered_points.append(point)
                continue

            thresholds = COV_THRESHOLDS.get(measurement)
            if thresholds is None:
                # Unknown measurement -- write anyway
                filtered_points.append(point)
                continue

            cov_key = _build_cov_key(point)
            fields = point.get("fields", {})

            if self._cov.should_write(cov_key, fields, thresholds):
                self._cov.record_write(cov_key, fields)
                filtered_points.append(point)
            else:
                self._points_filtered += 1

        # 7. Write filtered points to InfluxDB
        if filtered_points:
            await self._influxdb.write_points(filtered_points)
            self._points_written += len(filtered_points)

        self._messages_processed += 1
        self._last_message_at = time.time()

    def get_stats(self) -> dict[str, Any]:
        """Return ingestion statistics."""
        return {
            "running": self._running,
            "queue_size": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "messages_processed": self._messages_processed,
            "messages_dropped": self._messages_dropped,
            "points_extracted": self._points_extracted,
            "points_written": self._points_written,
            "points_filtered": self._points_filtered,
            "last_message_at": self._last_message_at,
        }
```

### 2b. Run tests -- expect all green

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_ingestion_service.py -x -v
```

### 2c. Verify existing tests still pass

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/ -x -v --timeout=30
```

### 2d. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/services/ingestion_service.py
git commit -m "$(cat <<'EOF'
feat(telemetry): implement IngestionService with CoV filtering and cache updates

Consumes WebSocket messages from asyncio.Queue, dispatches to device-type
extractors, applies per-measurement CoV filtering with configurable thresholds,
writes filtered points to InfluxDB, and updates the LatestValueCache.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 3 -- MistWsManager: write failing tests

- [ ] Create test file

**Create file:** `backend/tests/unit/test_mist_ws_manager.py`

```python
"""Unit tests for MistWsManager.

The WS manager wraps thread-based mistapi.websockets.sites.DeviceStatsEvents.
We test the logic (site chunking, state management, status reporting) with
mocked DeviceStatsEvents, NOT actual WebSocket connections.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ws(ready: bool = True):
    """Create a mock DeviceStatsEvents instance."""
    ws = MagicMock()
    ws.ready.return_value = ready
    ws.connect.return_value = None
    ws.disconnect.return_value = None
    ws.on_message.return_value = None
    return ws


def _make_queue() -> asyncio.Queue:
    return asyncio.Queue(maxsize=10_000)


def _make_api_session() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: construction
# ---------------------------------------------------------------------------


class TestMistWsManagerInit:
    """Test construction and initial state."""

    def test_creates_with_session_and_queue(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        assert mgr._connections == []
        assert mgr._subscribed_sites == []

    def test_initial_status(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        status = mgr.get_status()
        assert status["connections"] == 0
        assert status["sites_subscribed"] == 0
        assert status["all_ready"] is True  # vacuously true with no connections


# ---------------------------------------------------------------------------
# Tests: site chunking
# ---------------------------------------------------------------------------


class TestMistWsManagerChunking:
    """Test that sites are grouped into chunks of 1000."""

    def test_chunk_sites_small(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(50)]
        chunks = mgr._chunk_sites(sites)
        assert len(chunks) == 1
        assert len(chunks[0]) == 50

    def test_chunk_sites_exactly_1000(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(1000)]
        chunks = mgr._chunk_sites(sites)
        assert len(chunks) == 1
        assert len(chunks[0]) == 1000

    def test_chunk_sites_over_1000(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(1500)]
        chunks = mgr._chunk_sites(sites)
        assert len(chunks) == 2
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 500

    def test_chunk_sites_empty(self):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        chunks = mgr._chunk_sites([])
        assert chunks == []


# ---------------------------------------------------------------------------
# Tests: start with mocked DeviceStatsEvents
# ---------------------------------------------------------------------------


class TestMistWsManagerStart:
    """Test start creates connections for site chunks."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_creates_one_connection_for_small_list(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws_cls.return_value = _make_mock_ws()

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1", "site-2", "site-3"])

        assert mock_ws_cls.call_count == 1
        assert len(mgr._connections) == 1
        assert mgr._subscribed_sites == ["site-1", "site-2", "site-3"]

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_creates_two_connections_for_1500_sites(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws_cls.return_value = _make_mock_ws()

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        sites = [f"site-{i}" for i in range(1500)]
        await mgr.start(sites)

        assert mock_ws_cls.call_count == 2
        assert len(mgr._connections) == 2
        assert len(mgr._subscribed_sites) == 1500

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_registers_on_message_callback(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])

        mock_ws.on_message.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_calls_connect_with_background(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])

        mock_ws.connect.assert_called_once_with(run_in_background=True)

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_start_with_empty_sites_does_nothing(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start([])

        assert mock_ws_cls.call_count == 0
        assert mgr._connections == []


# ---------------------------------------------------------------------------
# Tests: stop
# ---------------------------------------------------------------------------


class TestMistWsManagerStop:
    """Test stop disconnects all connections."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_stop_disconnects_all(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])
        await mgr.stop()

        mock_ws.disconnect.assert_called_once()
        assert mgr._connections == []
        assert mgr._subscribed_sites == []


# ---------------------------------------------------------------------------
# Tests: get_status
# ---------------------------------------------------------------------------


class TestMistWsManagerStatus:
    """Test status reporting."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_status_after_start(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws(ready=True)
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1", "site-2"])

        status = mgr.get_status()
        assert status["connections"] == 1
        assert status["sites_subscribed"] == 2
        assert status["all_ready"] is True

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_status_not_ready(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws(ready=False)
        mock_ws_cls.return_value = mock_ws

        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=_make_queue(),
        )
        await mgr.start(["site-1"])

        status = mgr.get_status()
        assert status["all_ready"] is False


# ---------------------------------------------------------------------------
# Tests: message bridging callback
# ---------------------------------------------------------------------------


class TestMistWsManagerBridge:
    """Test the thread-to-asyncio message bridge callback."""

    @pytest.mark.asyncio
    @patch("app.modules.telemetry.services.mist_ws_manager.DeviceStatsEvents")
    async def test_bridge_callback_puts_message_in_queue(self, mock_ws_cls):
        from app.modules.telemetry.services.mist_ws_manager import MistWsManager

        mock_ws = _make_mock_ws()
        mock_ws_cls.return_value = mock_ws

        queue = _make_queue()
        mgr = MistWsManager(
            api_session=_make_api_session(),
            message_queue=queue,
        )
        await mgr.start(["site-1"])

        # Get the callback that was registered
        callback = mock_ws.on_message.call_args[0][0]

        # Simulate calling it (as the WS thread would)
        # The callback should use loop.call_soon_threadsafe
        # We test by directly invoking _on_ws_message which is the bridge method
        test_msg = {"event": "data", "channel": "/sites/s1/stats/devices", "data": "{}"}
        mgr._on_ws_message(test_msg)

        # Give the event loop a chance to process
        await asyncio.sleep(0.05)

        assert queue.qsize() == 1
        assert queue.get_nowait() == test_msg

        await mgr.stop()
```

### 3b. Run tests -- expect failures (module not found)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_mist_ws_manager.py -x -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.modules.telemetry.services.mist_ws_manager'`

### 3c. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add tests/unit/test_mist_ws_manager.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add failing tests for MistWsManager

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 4 -- MistWsManager: implement to pass all tests

- [ ] Create WS manager

**Create file:** `backend/app/modules/telemetry/services/mist_ws_manager.py`

```python
"""Mist WebSocket Manager — lifecycle, auto-scaling, and thread-to-asyncio bridging.

Manages one or more ``mistapi.websockets.sites.DeviceStatsEvents`` connections.
Each connection handles up to 1000 site subscriptions. Messages received on
background WS threads are bridged into an ``asyncio.Queue`` via
``loop.call_soon_threadsafe()``.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import structlog
from mistapi.websockets.sites import DeviceStatsEvents

logger = structlog.get_logger(__name__)

_MAX_SITES_PER_CONNECTION = 1000


class MistWsManager:
    """Manages Mist WebSocket connections for device stats streaming."""

    def __init__(
        self,
        api_session: Any,
        message_queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        self._api_session = api_session
        self._message_queue = message_queue
        self._connections: list[DeviceStatsEvents] = []
        self._subscribed_sites: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None

        # Stats
        self._messages_received = 0
        self._messages_bridge_dropped = 0
        self._last_message_at: float = 0
        self._started_at: float = 0

    def _chunk_sites(self, site_ids: list[str]) -> list[list[str]]:
        """Split site_ids into chunks of _MAX_SITES_PER_CONNECTION."""
        if not site_ids:
            return []
        n = _MAX_SITES_PER_CONNECTION
        return [site_ids[i : i + n] for i in range(0, len(site_ids), n)]

    def _on_ws_message(self, msg: dict[str, Any]) -> None:
        """Callback invoked from the WS thread — bridge message to asyncio.

        Uses ``loop.call_soon_threadsafe()`` to safely post the message into
        the asyncio queue from a non-asyncio thread.
        """
        self._messages_received += 1
        self._last_message_at = time.time()

        if self._loop is None:
            return

        try:
            self._loop.call_soon_threadsafe(self._message_queue.put_nowait, msg)
        except asyncio.QueueFull:
            self._messages_bridge_dropped += 1
            logger.debug("ws_bridge_queue_full")
        except RuntimeError:
            # Event loop closed
            pass

    async def start(self, site_ids: list[str]) -> None:
        """Subscribe to device stats for all sites, auto-scaling connections.

        Creates one ``DeviceStatsEvents`` per chunk of 1000 sites, registers
        the bridge callback, and starts each in a background thread.
        """
        self._loop = asyncio.get_running_loop()
        self._subscribed_sites = list(site_ids)
        chunks = self._chunk_sites(site_ids)

        if not chunks:
            logger.info("mist_ws_manager_no_sites")
            return

        for i, chunk in enumerate(chunks):
            ws = DeviceStatsEvents(
                mist_session=self._api_session,
                site_ids=chunk,
                auto_reconnect=True,
                max_reconnect_attempts=5,
                reconnect_backoff=2.0,
            )
            ws.on_message(self._on_ws_message)
            ws.connect(run_in_background=True)
            self._connections.append(ws)

        self._started_at = time.time()
        logger.info(
            "mist_ws_manager_started",
            connections=len(self._connections),
            sites=len(self._subscribed_sites),
        )

    async def stop(self) -> None:
        """Disconnect all WebSocket connections."""
        for ws in self._connections:
            try:
                ws.disconnect()
            except Exception as e:
                logger.warning("mist_ws_disconnect_error", error=str(e))

        count = len(self._connections)
        self._connections = []
        self._subscribed_sites = []
        self._loop = None

        logger.info(
            "mist_ws_manager_stopped",
            connections_closed=count,
            messages_received=self._messages_received,
        )

    async def add_sites(self, site_ids: list[str]) -> None:
        """Dynamically subscribe to new sites.

        Determines if sites fit in an existing connection or creates new ones.
        For simplicity in this initial implementation, stops all connections
        and restarts with the combined list.
        """
        combined = list(set(self._subscribed_sites + site_ids))
        await self.stop()
        await self.start(combined)

    async def remove_sites(self, site_ids: list[str]) -> None:
        """Unsubscribe from sites.

        Stops all connections and restarts without the removed sites.
        """
        remaining = [s for s in self._subscribed_sites if s not in set(site_ids)]
        await self.stop()
        if remaining:
            await self.start(remaining)

    def get_status(self) -> dict[str, Any]:
        """Return connection status, site count, and message stats."""
        ready_list = []
        for ws in self._connections:
            try:
                ready_list.append(ws.ready())
            except Exception:
                ready_list.append(False)

        return {
            "connections": len(self._connections),
            "sites_subscribed": len(self._subscribed_sites),
            "all_ready": all(ready_list) if ready_list else True,
            "connections_ready": sum(1 for r in ready_list if r),
            "messages_received": self._messages_received,
            "messages_bridge_dropped": self._messages_bridge_dropped,
            "last_message_at": self._last_message_at,
            "started_at": self._started_at,
        }
```

### 4b. Run tests -- expect all green

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/test_mist_ws_manager.py -x -v
```

### 4c. Run the full unit test suite

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/ -x -v --timeout=30
```

### 4d. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/services/mist_ws_manager.py
git commit -m "$(cat <<'EOF'
feat(telemetry): implement MistWsManager with auto-scaling and thread bridge

Manages mistapi DeviceStatsEvents connections with automatic chunking at
1000 sites per connection. Bridges WS thread messages to asyncio.Queue via
loop.call_soon_threadsafe().

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 5 -- Update telemetry module singletons

- [ ] Update `__init__.py`

**Edit file:** `backend/app/modules/telemetry/__init__.py`

Replace the entire contents with:

```python
"""Telemetry module — WebSocket device stats ingestion pipeline.

Module-level singletons are initialized during app startup when
telemetry_enabled is True in SystemConfig.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.telemetry.services.cov_filter import CoVFilter
    from app.modules.telemetry.services.influxdb_service import InfluxDBService
    from app.modules.telemetry.services.ingestion_service import IngestionService
    from app.modules.telemetry.services.latest_value_cache import LatestValueCache
    from app.modules.telemetry.services.mist_ws_manager import MistWsManager

_influxdb_service: InfluxDBService | None = None
_latest_cache: LatestValueCache | None = None
_cov_filter: CoVFilter | None = None
_ingestion_service: IngestionService | None = None
_ws_manager: MistWsManager | None = None
```

### 5b. Verify types pass

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/mypy app/modules/telemetry/__init__.py --no-error-summary
```

### 5c. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/__init__.py
git commit -m "$(cat <<'EOF'
feat(telemetry): add ingestion, ws_manager, and cov_filter singletons to module init

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 6 -- Wire into main.py lifespan

- [ ] Update startup and shutdown

**Edit file:** `backend/app/main.py`

Find the existing telemetry startup block (lines 99-124, beginning with `# Start telemetry pipeline if enabled`). Replace that entire try/except block with:

```python
        # Start telemetry pipeline if enabled
        try:
            from app.models.system import SystemConfig as _SystemConfig

            _telemetry_config = await _SystemConfig.get_config()
            if (
                _telemetry_config.telemetry_enabled
                and _telemetry_config.influxdb_url
                and _telemetry_config.influxdb_token
            ):
                import app.modules.telemetry as telemetry_mod
                from app.core.security import decrypt_sensitive_data
                from app.modules.telemetry.services.cov_filter import CoVFilter
                from app.modules.telemetry.services.influxdb_service import InfluxDBService
                from app.modules.telemetry.services.ingestion_service import IngestionService
                from app.modules.telemetry.services.latest_value_cache import LatestValueCache
                from app.modules.telemetry.services.mist_ws_manager import MistWsManager

                # 1. Foundation services
                telemetry_mod._latest_cache = LatestValueCache()
                telemetry_mod._cov_filter = CoVFilter()
                telemetry_mod._influxdb_service = InfluxDBService(
                    url=_telemetry_config.influxdb_url,
                    token=decrypt_sensitive_data(_telemetry_config.influxdb_token),
                    org=_telemetry_config.influxdb_org or "mist_automation",
                    bucket=_telemetry_config.influxdb_bucket or "mist_telemetry",
                )
                await telemetry_mod._influxdb_service.start()

                # 2. Ingestion service
                telemetry_mod._ingestion_service = IngestionService(
                    influxdb=telemetry_mod._influxdb_service,
                    cache=telemetry_mod._latest_cache,
                    cov_filter=telemetry_mod._cov_filter,
                    org_id=_telemetry_config.mist_org_id or settings.mist_org_id or "",
                )
                await telemetry_mod._ingestion_service.start()

                # 3. WebSocket manager — connect to Mist
                try:
                    from app.services.mist_service_factory import create_mist_service

                    mist = await create_mist_service()
                    sites = await mist.get_sites()
                    site_ids = [s["id"] for s in sites if s.get("id")]

                    if site_ids:
                        telemetry_mod._ws_manager = MistWsManager(
                            api_session=mist.get_session(),
                            message_queue=telemetry_mod._ingestion_service.get_queue(),
                        )
                        await telemetry_mod._ws_manager.start(site_ids)
                        logger.info(
                            "telemetry_ws_started",
                            sites=len(site_ids),
                        )
                    else:
                        logger.warning("telemetry_no_sites_found")
                except Exception as e:
                    logger.warning("telemetry_ws_start_failed", error=str(e))

                logger.info("telemetry_started")
        except Exception as e:
            logger.warning("telemetry_start_failed", error=str(e))
```

Find the existing telemetry shutdown block (lines 141-149, beginning with `# Stop telemetry pipeline`). Replace with:

```python
        # Stop telemetry pipeline
        try:
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

            telemetry_mod._cov_filter = None
            telemetry_mod._latest_cache = None
            logger.info("telemetry_stopped")
        except Exception:
            pass
```

### 6b. Verify the app starts without errors (if telemetry is disabled, the new code is a no-op)

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/python -c "
import asyncio
from unittest.mock import AsyncMock, patch

async def test():
    # Verify the import structure works
    import app.modules.telemetry as t
    assert hasattr(t, '_ingestion_service')
    assert hasattr(t, '_ws_manager')
    assert hasattr(t, '_cov_filter')
    print('All telemetry singletons declared correctly')

asyncio.run(test())
"
```

### 6c. Run the full test suite to verify no regressions

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/ -x -v --timeout=30
```

### 6d. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/main.py
git commit -m "$(cat <<'EOF'
feat(telemetry): wire IngestionService and MistWsManager into app lifespan

Startup: creates CoVFilter, IngestionService, fetches org sites, creates
MistWsManager with auto-scaling WS connections. Shutdown: stops in reverse
order (WS -> ingestion -> InfluxDB).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 7 -- Enhance /telemetry/status with WS + ingestion info

- [ ] Update router

**Edit file:** `backend/app/modules/telemetry/router.py`

Replace the entire contents with:

```python
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

    result: dict[str, Any] = {
        "enabled": telemetry_mod._influxdb_service is not None,
        "influxdb": telemetry_mod._influxdb_service.get_stats() if telemetry_mod._influxdb_service else None,
        "cache_size": telemetry_mod._latest_cache.size() if telemetry_mod._latest_cache else 0,
        "websocket": telemetry_mod._ws_manager.get_status() if telemetry_mod._ws_manager else None,
        "ingestion": telemetry_mod._ingestion_service.get_stats() if telemetry_mod._ingestion_service else None,
    }
    return result
```

### 7b. Verify no import errors

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/python -c "from app.modules.telemetry.router import router; print('Router OK, routes:', [r.path for r in router.routes])"
```

### 7c. Run all tests

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/ -x -v --timeout=30
```

### 7d. Commit

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add app/modules/telemetry/router.py
git commit -m "$(cat <<'EOF'
feat(telemetry): enhance /telemetry/status with websocket and ingestion stats

Now returns ws connection count, sites subscribed, all_ready flag, ingestion
queue depth, messages processed, and CoV filtering stats.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Step 8 -- Code quality checks

- [ ] Run linting and type checks

### 8a. Run black formatting

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/black app/modules/telemetry/services/ingestion_service.py app/modules/telemetry/services/mist_ws_manager.py app/modules/telemetry/__init__.py app/modules/telemetry/router.py app/main.py tests/unit/test_ingestion_service.py tests/unit/test_mist_ws_manager.py
```

### 8b. Run ruff linting

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/ruff check app/modules/telemetry/services/ingestion_service.py app/modules/telemetry/services/mist_ws_manager.py app/modules/telemetry/__init__.py app/modules/telemetry/router.py tests/unit/test_ingestion_service.py tests/unit/test_mist_ws_manager.py
```

Fix any issues reported by ruff:

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/ruff check --fix app/modules/telemetry/services/ingestion_service.py app/modules/telemetry/services/mist_ws_manager.py tests/unit/test_ingestion_service.py tests/unit/test_mist_ws_manager.py
```

### 8c. Run mypy type checking

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/mypy app/modules/telemetry/ --no-error-summary
```

### 8d. Run full test suite one final time

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
.venv/bin/pytest tests/unit/ -x -v --timeout=30
```

### 8e. Commit any formatting/lint fixes

```bash
cd /Users/tmunzer/4_dev/mist_automation/backend
git add -A
git diff --cached --name-only | head -20
git commit -m "$(cat <<'EOF'
style(telemetry): apply black formatting and ruff fixes to Plan 3 files

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Summary of all files touched

### New files (4):
- `backend/app/modules/telemetry/services/ingestion_service.py`
- `backend/app/modules/telemetry/services/mist_ws_manager.py`
- `backend/tests/unit/test_ingestion_service.py`
- `backend/tests/unit/test_mist_ws_manager.py`

### Modified files (3):
- `backend/app/modules/telemetry/__init__.py` -- added `_cov_filter`, `_ingestion_service`, `_ws_manager` singletons
- `backend/app/main.py` -- expanded startup/shutdown to create and wire IngestionService + MistWsManager
- `backend/app/modules/telemetry/router.py` -- added `websocket` and `ingestion` keys to `/telemetry/status`

---

### Critical Files for Implementation
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/services/ingestion_service.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/services/mist_ws_manager.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/main.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/__init__.py`
- `/Users/tmunzer/4_dev/mist_automation/backend/app/modules/telemetry/router.py`
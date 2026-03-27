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

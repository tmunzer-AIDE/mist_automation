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

from app.core.websocket import ws_manager
from app.modules.telemetry.extractors import extract_points
from app.modules.telemetry.services.cov_filter import CoVFilter
from app.modules.telemetry.services.influxdb_service import InfluxDBService
from app.modules.telemetry.services.latest_value_cache import LatestValueCache

logger = structlog.get_logger(__name__)

# Regex to extract site_id and stat type from channel: /sites/{uuid}/stats/(devices|clients)
_CHANNEL_RE = re.compile(r"/sites/([^/]+)/stats/(devices|clients)")

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
    "switch_dhcp": {
        "num_ips": "exact",
        "num_leased": "exact",
        "utilization_pct": 3.0,
    },
    "client_stats": {
        "rssi": 3.0,
        "snr": 3.0,
        "channel": "exact",
        "tx_rate": "exact",
        "rx_rate": "exact",
        "tx_bps": "always",
        "rx_bps": "always",
        "tx_pkts": "always",
        "rx_pkts": "always",
        "tx_bytes": "always",
        "rx_bytes": "always",
        "tx_retries": "always",
        "rx_retries": "always",
        "idle_time": 5.0,
        "uptime": "always",
        "hostname": "exact",
        "ip": "exact",
        "group": "exact",
        "vlan_id": "exact",
        "proto": "exact",
        "username": "exact",
        "manufacture": "exact",
        "os": "exact",
        "os_version": "exact",
        "key_mgmt": "exact",
        "type": "exact",
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


def _build_device_ws_event(payload: dict[str, Any], device_type: str) -> dict[str, Any]:
    """Build a WebSocket broadcast payload from a raw device stats message.

    Extracts the relevant summary + detail fields per device type so frontend
    clients on the live device page receive a compact, pre-shaped event.
    """
    ts = int(payload.get("last_seen") or payload.get("_time") or time.time())
    event: dict[str, Any] = {"device_type": device_type, "timestamp": ts}
    event["raw"] = payload

    if device_type == "ap":
        event["summary"] = _build_ap_summary(payload)
        event["bands"] = _build_ap_bands(payload)

    elif device_type == "switch":
        event["summary"] = _build_switch_summary(payload)
        event["ports"] = _build_switch_ports(payload)
        event["modules"] = _build_switch_modules(payload)
        event["dhcp"] = _build_dhcp(payload)

    elif device_type == "gateway":
        event["summary"] = _build_gateway_summary(payload)
        event["wan"] = _build_gateway_wan(payload)
        event["dhcp"] = _build_dhcp(payload)
        spu = _build_gateway_spu(payload)
        if spu:
            event["spu"] = spu
        cluster = _build_gateway_cluster(payload)
        if cluster:
            event["cluster"] = cluster
        resources = _build_gateway_resources(payload)
        if resources:
            event["resources"] = resources

    return event


def _build_client_ws_event(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": int(payload.get("last_seen") or time.time()),
        "rssi": payload.get("rssi"),
        "snr": payload.get("snr"),
        "band": str(payload.get("band") or ""),
        "channel": payload.get("channel"),
        "tx_bps": int(payload.get("tx_bps") or 0),
        "rx_bps": int(payload.get("rx_bps") or 0),
        "tx_rate": payload.get("tx_rate"),
        "rx_rate": payload.get("rx_rate"),
        "ap_mac": payload.get("ap_mac") or "",
        "ssid": payload.get("ssid") or "",
        "proto": payload.get("proto") or "",
        "raw": payload,
    }


# ---------------------------------------------------------------------------
# Per-device-type WS event builders
# ---------------------------------------------------------------------------


def _build_ap_summary(payload: dict[str, Any]) -> dict[str, Any]:
    cpu_util = int(payload.get("cpu_util", 0))
    mem_total = payload.get("mem_total_kb", 0)
    mem_used = payload.get("mem_used_kb", 0)
    if mem_total > 0:
        mem_usage = int(mem_used / mem_total * 100)
    else:
        memory_stat = payload.get("memory_stat", {})
        mem_usage = int(memory_stat.get("usage", 0))
    return {
        "cpu_util": cpu_util,
        "mem_usage": mem_usage,
        "num_clients": int(payload.get("num_clients", 0)),
        "uptime": int(payload.get("uptime", 0)),
    }


def _build_ap_bands(payload: dict[str, Any]) -> list[dict[str, Any]]:
    radio_stat = payload.get("radio_stat")
    if not radio_stat:
        return []
    bands: list[dict[str, Any]] = []
    for band_key in ("band_24", "band_5", "band_6"):
        bd = radio_stat.get(band_key)
        if not bd or bd.get("disabled", False):
            continue
        bands.append(
            {
                "band": band_key,
                "util_all": bd.get("util_all", 0),
                "num_clients": bd.get("num_clients", 0),
                "noise_floor": bd.get("noise_floor", 0),
                "channel": bd.get("channel", 0),
                "power": bd.get("power", 0),
                "bandwidth": bd.get("bandwidth", 0),
            }
        )
    return bands


def _build_switch_summary(payload: dict[str, Any]) -> dict[str, Any]:
    cpu_stat = payload.get("cpu_stat", {})
    cpu_util = int(100 - cpu_stat.get("idle", 100))
    memory_stat = payload.get("memory_stat", {})
    mem_usage = int(memory_stat.get("usage", 0))

    # Client count
    clients_stats = payload.get("clients_stats")
    if clients_stats:
        num_clients = clients_stats.get("total", {}).get("num_wired_clients", 0) or 0
    else:
        clients = payload.get("clients")
        num_clients = len(clients) if clients else 0

    # PoE totals
    poe_draw_total = 0.0
    poe_max_total = 0.0
    for mod in payload.get("module_stat", []):
        poe = mod.get("poe")
        if poe:
            poe_draw_total += poe.get("power_draw", 0.0)
            poe_max_total += poe.get("max_power", 0.0)

    return {
        "cpu_util": cpu_util,
        "mem_usage": mem_usage,
        "num_clients": num_clients,
        "uptime": int(payload.get("uptime", 0)),
        "poe_draw_total": poe_draw_total,
        "poe_max_total": poe_max_total,
    }


def _build_switch_ports(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if_stat = payload.get("if_stat")
    if not if_stat:
        return []
    ports: list[dict[str, Any]] = []
    for if_key, port_data in if_stat.items():
        if not port_data.get("up", False):
            continue
        ports.append(
            {
                "port_id": port_data.get("port_id", if_key),
                "speed": port_data.get("speed", 0),
                "tx_pkts": port_data.get("tx_pkts", 0),
                "rx_pkts": port_data.get("rx_pkts", 0),
            }
        )
    return ports


def _build_switch_modules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    modules = payload.get("module_stat")
    if not modules:
        return []
    result: list[dict[str, Any]] = []
    for mod in modules:
        temperatures = mod.get("temperatures", [])
        temp_max = max((t.get("celsius", 0) for t in temperatures), default=0)
        poe = mod.get("poe", {})
        poe_draw = poe.get("power_draw", 0.0) if poe else 0.0
        # vc_links only contains UP links — len() is the count of active links
        vc_links = mod.get("vc_links", [])
        result.append(
            {
                "fpc_idx": mod.get("_idx", 0),
                "vc_role": mod.get("vc_role", ""),
                "temp_max": temp_max,
                "poe_draw": poe_draw,
                "vc_links_count": len(vc_links),
                "mem_usage": mod.get("memory_stat", {}).get("usage", 0),
            }
        )
    return result


def _build_dhcp(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build DHCP scope list — shared by switch and gateway."""
    dhcpd_stat = payload.get("dhcpd_stat")
    if not dhcpd_stat:
        return []
    result: list[dict[str, Any]] = []
    for network_name, scope_data in dhcpd_stat.items():
        num_ips = scope_data.get("num_ips", 0)
        num_leased = scope_data.get("num_leased", 0)
        utilization_pct = round(num_leased / num_ips * 100, 1) if num_ips > 0 else 0.0
        result.append(
            {
                "network_name": network_name,
                "num_ips": num_ips,
                "num_leased": num_leased,
                "utilization_pct": utilization_pct,
            }
        )
    return result


def _build_gateway_summary(payload: dict[str, Any]) -> dict[str, Any]:
    cpu_stat = payload.get("cpu_stat", {})
    cpu_util = int(100 - cpu_stat.get("idle", 100))
    memory_stat = payload.get("memory_stat", {})
    mem_usage = int(memory_stat.get("usage", 0))
    return {
        "cpu_util": cpu_util,
        "mem_usage": mem_usage,
        "uptime": int(payload.get("uptime", 0)),
        "ha_state": payload.get("ha_state", ""),
        "config_status": payload.get("config_status", ""),
    }


def _build_gateway_wan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if_stat = payload.get("if_stat")
    if not if_stat:
        return []
    wan_ports: list[dict[str, Any]] = []
    for _if_key, port_data in if_stat.items():
        if port_data.get("port_usage") != "wan":
            continue
        wan_ports.append(
            {
                "port_id": port_data.get("port_id", _if_key),
                "wan_name": port_data.get("wan_name", ""),
                "up": port_data.get("up", False),
                "tx_bytes": port_data.get("tx_bytes", 0),
                "rx_bytes": port_data.get("rx_bytes", 0),
                "tx_pkts": port_data.get("tx_pkts", 0),
                "rx_pkts": port_data.get("rx_pkts", 0),
            }
        )
    return wan_ports


def _build_gateway_spu(payload: dict[str, Any]) -> dict[str, Any] | None:
    spu_stat = payload.get("spu_stat")
    if not spu_stat:
        return None
    spu = spu_stat[0]
    return {
        "spu_cpu": spu.get("spu_cpu", 0),
        "spu_sessions": spu.get("spu_current_session", 0),
        "spu_max_sessions": spu.get("spu_max_session", 0),
        "spu_memory": spu.get("spu_memory", 0),
    }


def _build_gateway_cluster(payload: dict[str, Any]) -> dict[str, Any] | None:
    cluster_config = payload.get("cluster_config")
    if not cluster_config:
        return None
    control_link_info = cluster_config.get("control_link_info", {})
    control_link_up = control_link_info.get("status", "").lower() == "up"
    fabric_link_info = cluster_config.get("fabric_link_info", {})
    fabric_status = fabric_link_info.get("Status", fabric_link_info.get("status", ""))
    fabric_link_up = fabric_status.lower() in ("up", "enabled")
    return {
        "status": cluster_config.get("status", ""),
        "operational": cluster_config.get("operational", ""),
        "primary_health": cluster_config.get("primary_node_health", ""),
        "secondary_health": cluster_config.get("secondary_node_health", ""),
        "control_link_up": control_link_up,
        "fabric_link_up": fabric_link_up,
    }


def _build_gateway_resources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    module_stat = payload.get("module_stat")
    if not module_stat:
        return []
    first_module = module_stat[0]
    network_resources = first_module.get("network_resources")
    if not network_resources:
        return []
    result: list[dict[str, Any]] = []
    for resource in network_resources:
        count = resource.get("count", 0)
        limit = resource.get("limit", 0)
        utilization_pct = round(count / limit * 100, 1) if limit > 0 else 0.0
        result.append(
            {
                "resource_type": resource.get("type", ""),
                "count": count,
                "limit": limit,
                "utilization_pct": utilization_pct,
            }
        )
    return result


class IngestionService:
    """Consumes WS messages from a queue, extracts metrics, and writes to InfluxDB + cache."""

    def __init__(
        self,
        influxdb: InfluxDBService,
        cache: LatestValueCache,
        cov_filter: CoVFilter,
        org_id: str,
        client_cache: Any | None = None,
        queue_maxsize: int = 10_000,
    ) -> None:
        self._influxdb = influxdb
        self._cache = cache
        self._cov = cov_filter
        self._org_id = org_id
        self._client_cache = client_cache
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = False
        self._task: asyncio.Task | None = None

        # Stats
        self._messages_processed = 0
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

        # 2. Extract site_id and stat_type from channel
        channel = msg.get("channel", "")
        match = _CHANNEL_RE.search(channel)
        if not match:
            logger.debug("ingestion_unknown_channel", channel=channel)
            return
        site_id = match.group(1)
        stat_type = match.group(2)

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

        # Dispatch to client pipeline if channel is /stats/clients
        if stat_type == "clients":
            await self._process_client_message(site_id, payload)
            return

        # 4. Update LatestValueCache with the full payload.
        # Skip basic AP messages (no "type" and no "model") — they lack identifying info and
        # arrive milliseconds before the full stats message, so caching them would overwrite a
        # rich entry with a stripped-down one until the full stats arrives.
        # Also inject site_id from the channel into the payload: AP payloads don't include it,
        # which would break site-level filtering in scope queries.
        mac = payload.get("mac", "")
        has_type_info = bool(payload.get("type") or payload.get("model"))
        if mac and has_type_info:
            if not payload.get("site_id"):
                payload = {**payload, "site_id": site_id}
            self._cache.update(mac, payload)

        # 5. Extract InfluxDB data points
        device_type = payload.get("type") or ("ap" if isinstance(payload.get("model"), str) and payload["model"].startswith("AP") else None)
        has_time = payload.get("_time") is not None
        points = extract_points(payload, self._org_id, site_id)
        self._points_extracted += len(points)

        measurements = {p.get("measurement") for p in points} if points else set()
        logger.debug(
            "ingestion_message_processed",
            mac=mac,
            device_type=device_type,
            has_time=has_time,
            points_extracted=len(points),
            measurements=sorted(measurements),
        )

        if not points:
            # Still count as processed (e.g., basic AP messages are skipped for cache + InfluxDB)
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
            filtered_measurements = {}
            for p in filtered_points:
                m = p.get("measurement", "")
                filtered_measurements[m] = filtered_measurements.get(m, 0) + 1
            logger.debug(
                "ingestion_writing_points",
                mac=mac,
                device_type=device_type,
                total=len(filtered_points),
                measurements=filtered_measurements,
            )
            await self._influxdb.write_points(filtered_points)
            self._points_written += len(filtered_points)

        # 8. Broadcast to any live device page subscribers
        if mac and device_type:
            event = _build_device_ws_event(payload, device_type)
            await ws_manager.broadcast(f"telemetry:device:{mac}", event)

        # Broadcast lightweight refresh signals to site and org channels
        if site_id and mac and device_type:
            tick = {"mac": mac, "device_type": device_type}
            await ws_manager.broadcast(f"telemetry:site:{site_id}", tick)
            await ws_manager.broadcast("telemetry:org", tick)

        self._messages_processed += 1
        self._last_message_at = time.time()

        # Periodic cache pruning (every 1000 messages)
        if self._messages_processed % 1000 == 0:
            self._cache.prune(max_age_seconds=3600)

    async def _process_client_message(self, site_id: str, payload: dict[str, Any]) -> None:
        """Process a single client stats message: cache → CoV filter → InfluxDB → WS broadcast."""
        from app.modules.telemetry.extractors.client_extractor import extract_points as extract_client_points

        client_mac = payload.get("mac", "")
        if not client_mac:
            return

        # Inject site_id if missing
        if not payload.get("site_id"):
            payload = {**payload, "site_id": site_id}

        # Update client cache
        if self._client_cache is not None:
            self._client_cache.update(client_mac, payload)

        # Extract InfluxDB points (one point per client message)
        points = extract_client_points(payload, self._org_id, site_id)
        self._points_extracted += len(points)

        if not points:
            self._messages_processed += 1
            self._last_message_at = time.time()
            return

        # Apply CoV filtering
        filtered_points: list[dict[str, Any]] = []
        thresholds = COV_THRESHOLDS.get("client_stats", {})
        for point in points:
            cov_key = _build_cov_key(point)
            fields = point.get("fields", {})
            if self._cov.should_write(cov_key, fields, thresholds):
                self._cov.record_write(cov_key, fields)
                filtered_points.append(point)
            else:
                self._points_filtered += 1

        # Write to InfluxDB
        if filtered_points:
            await self._influxdb.write_points(filtered_points)
            self._points_written += len(filtered_points)

        # Broadcast rich event to per-client subscribers
        client_event = _build_client_ws_event(payload)
        await ws_manager.broadcast(f"telemetry:client:{client_mac}", client_event)

        # Broadcast lightweight tick to site channel (frontend debounces at 5s)
        tick = {"mac": client_mac, "type": "client"}
        await ws_manager.broadcast(f"telemetry:site:{site_id}", tick)

        self._messages_processed += 1
        self._last_message_at = time.time()

        # Periodic client cache pruning (every 1000 messages; 600s > _ttl=300)
        if self._messages_processed % 1000 == 0 and self._client_cache is not None:
            self._client_cache.prune(max_age_seconds=600)

    def get_stats(self) -> dict[str, Any]:
        """Return ingestion statistics."""
        return {
            "running": self._running,
            "queue_size": self._queue.qsize(),
            "queue_capacity": self._queue.maxsize,
            "messages_processed": self._messages_processed,
            "points_extracted": self._points_extracted,
            "points_written": self._points_written,
            "points_filtered": self._points_filtered,
            "last_message_at": self._last_message_at,
        }

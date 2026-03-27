"""Switch metric extractor — parses Mist switch WebSocket payloads into InfluxDB data points.

Produces:
- device_summary: cpu_util, mem_usage, num_clients, uptime, poe_draw_total, poe_max_total
- port_stats: per UP port — port_id, up, tx_pkts, rx_pkts, speed
- module_stats: per VC member — fpc_idx, temp_max, poe_draw, vc_role, vc_links_count, mem_usage
"""

from __future__ import annotations

from app.modules.telemetry.extractors._helpers import get_timestamp


def _get_name(payload: dict) -> str:
    """Get device name, falling back to hostname."""
    return payload.get("name") or payload.get("hostname") or ""


def _get_num_clients(payload: dict) -> int:
    """Get client count from clients_stats or len(clients)."""
    clients_stats = payload.get("clients_stats")
    if clients_stats:
        total = clients_stats.get("total", {})
        count = total.get("num_wired_clients")
        if count is not None:
            return count
    clients = payload.get("clients")
    if clients is not None:
        return len(clients)
    return 0


def _get_poe_totals(payload: dict) -> tuple[float, float]:
    """Sum PoE draw and max across all module_stat entries."""
    modules = payload.get("module_stat", [])
    draw_total = 0.0
    max_total = 0.0
    for mod in modules:
        poe = mod.get("poe")
        if poe:
            draw_total += poe.get("power_draw", 0.0)
            max_total += poe.get("max_power", 0.0)
    return draw_total, max_total


def _extract_device_summary(payload: dict, org_id: str, site_id: str, timestamp: int) -> dict:
    """Build device_summary data point from switch payload."""
    cpu_stat = payload.get("cpu_stat", {})
    cpu_idle = cpu_stat.get("idle", 100)
    cpu_util = 100 - cpu_idle

    memory_stat = payload.get("memory_stat", {})
    mem_usage = memory_stat.get("usage", 0)

    poe_draw_total, poe_max_total = _get_poe_totals(payload)

    return {
        "measurement": "device_summary",
        "tags": {
            "org_id": org_id,
            "site_id": site_id,
            "mac": payload.get("mac", ""),
            "device_type": "switch",
            "name": _get_name(payload),
            "model": payload.get("model", ""),
        },
        "fields": {
            "cpu_util": cpu_util,
            "mem_usage": mem_usage,
            "num_clients": _get_num_clients(payload),
            "uptime": payload.get("uptime", 0),
            "poe_draw_total": poe_draw_total,
            "poe_max_total": poe_max_total,
        },
        "time": timestamp,
    }


def _extract_port_stats(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Build port_stats data points for UP ports from if_stat.

    Only extracts from "fresh" messages (``_time`` present).  The Mist cloud
    sends two types of switch stats: cached (``_ttl=600``, no ``_time``) with
    stale counters, and fresh (``_ttl=190``, ``_time`` set) with real counters.
    """
    # Skip cached messages — their if_stat counters are stale.
    # Fresh messages have _time set; cached ones don't.
    # Use last_seen as the InfluxDB timestamp (not _time, which can be days old).
    if not payload.get("_time"):
        return []

    if_stat = payload.get("if_stat")
    if not if_stat:
        return []

    timestamp = get_timestamp(payload)

    points: list[dict] = []
    for _if_key, port_data in if_stat.items():
        if not port_data.get("up", False):
            continue

        points.append(
            {
                "measurement": "port_stats",
                "tags": {
                    "org_id": org_id,
                    "site_id": site_id,
                    "mac": payload.get("mac", ""),
                    "port_id": port_data.get("port_id", _if_key),
                },
                "fields": {
                    "up": True,
                    "tx_pkts": port_data.get("tx_pkts", 0),
                    "rx_pkts": port_data.get("rx_pkts", 0),
                    "speed": port_data.get("speed", 0),
                },
                "time": timestamp,
            }
        )

    return points


def _extract_module_stats(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build module_stats data points per VC member from module_stat."""
    modules = payload.get("module_stat")
    if not modules:
        return []

    points: list[dict] = []
    for mod in modules:
        temperatures = mod.get("temperatures", [])
        if temperatures:
            temp_max = max(t.get("celsius", 0) for t in temperatures)
        else:
            temp_max = 0

        poe = mod.get("poe", {})
        poe_draw = poe.get("power_draw", 0.0) if poe else 0.0

        points.append(
            {
                "measurement": "module_stats",
                "tags": {
                    "org_id": org_id,
                    "site_id": site_id,
                    "mac": payload.get("mac", ""),
                    "fpc_idx": str(mod.get("_idx", 0)),
                },
                "fields": {
                    "temp_max": temp_max,
                    "poe_draw": poe_draw,
                    "vc_role": mod.get("vc_role", ""),
                    "vc_links_count": len(mod.get("vc_links", [])),
                    "mem_usage": mod.get("memory_stat", {}).get("usage", 0),
                },
                "time": timestamp,
            }
        )

    return points


def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract InfluxDB data points from a raw switch WebSocket payload.

    Returns one device_summary point, plus port_stats for each UP port
    and module_stats for each VC member.
    """
    timestamp = get_timestamp(payload)
    points: list[dict] = []

    points.append(_extract_device_summary(payload, org_id, site_id, timestamp))
    points.extend(_extract_port_stats(payload, org_id, site_id))
    points.extend(_extract_module_stats(payload, org_id, site_id, timestamp))

    return points

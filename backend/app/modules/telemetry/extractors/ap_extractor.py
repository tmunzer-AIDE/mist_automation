"""AP metric extractor — parses Mist AP WebSocket payloads into InfluxDB data points.

Produces:
- device_summary: cpu_util, mem_usage, num_clients, uptime (always written)
- radio_stats: per-band channel, power, bandwidth, util_all, noise_floor, num_clients (CoV filtered)
"""

from __future__ import annotations

from app.modules.telemetry.extractors._helpers import get_timestamp

_BANDS = ("band_24", "band_5", "band_6")


def _extract_device_summary(payload: dict, org_id: str, site_id: str, timestamp: int) -> dict:
    """Build device_summary data point from AP payload."""
    mem_total = payload.get("mem_total_kb", 0)
    mem_used = payload.get("mem_used_kb", 0)
    mem_usage = int(mem_used / mem_total * 100) if mem_total > 0 else 0

    return {
        "measurement": "device_summary",
        "tags": {
            "org_id": org_id,
            "site_id": site_id,
            "mac": payload.get("mac", ""),
            "device_type": "ap",
            "name": payload.get("name", ""),
            "model": payload.get("model", ""),
        },
        "fields": {
            "cpu_util": int(payload.get("cpu_util", 0)),
            "mem_usage": mem_usage,
            "num_clients": int(payload.get("num_clients", 0)),
            "uptime": int(payload.get("uptime", 0)),
        },
        "time": timestamp,
    }


def _extract_radio_stats(payload: dict, org_id: str, site_id: str, timestamp: int) -> list[dict]:
    """Build radio_stats data points for each active band."""
    radio_stat = payload.get("radio_stat")
    if not radio_stat:
        return []

    points: list[dict] = []
    for band in _BANDS:
        band_data = radio_stat.get(band)
        if not band_data:
            continue
        if band_data.get("disabled", False):
            continue

        points.append(
            {
                "measurement": "radio_stats",
                "tags": {
                    "org_id": org_id,
                    "site_id": site_id,
                    "mac": payload.get("mac", ""),
                    "band": band,
                },
                "fields": {
                    "channel": band_data.get("channel", 0),
                    "power": band_data.get("power", 0),
                    "bandwidth": band_data.get("bandwidth", 0),
                    "util_all": band_data.get("util_all", 0),
                    "noise_floor": band_data.get("noise_floor", 0),
                    "num_clients": band_data.get("num_clients", 0),
                },
                "time": timestamp,
            }
        )

    return points


def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract InfluxDB data points from a raw AP WebSocket payload.

    Skips "basic" messages (no ``model`` field) and returns an empty list.
    For full-stats messages, returns one device_summary point plus one
    radio_stats point per active (non-disabled) band.
    """
    # Skip basic messages — they lack the model field
    if not payload.get("model"):
        return []

    timestamp = get_timestamp(payload)
    points: list[dict] = []

    points.append(_extract_device_summary(payload, org_id, site_id, timestamp))
    points.extend(_extract_radio_stats(payload, org_id, site_id, timestamp))

    return points

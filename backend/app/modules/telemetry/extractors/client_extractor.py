# backend/app/modules/telemetry/extractors/client_extractor.py
"""Wireless client metric extractor — parses Mist client WebSocket payloads into InfluxDB data points.

Each message is one client record from the /sites/{id}/stats/clients channel.
Produces one `client_stats` measurement point per message.
"""

from __future__ import annotations

from app.modules.telemetry.extractors._helpers import get_timestamp


def extract_points(payload: dict, org_id: str, site_id: str) -> list[dict]:
    """Extract an InfluxDB data point from a Mist client stats payload.

    Returns a single-element list, or empty list if the payload lacks a MAC.
    """
    mac = payload.get("mac", "")
    if not mac:
        return []

    timestamp = get_timestamp(payload)

    key_mgmt = payload.get("key_mgmt", "") or ""
    auth_type = "eap" if "EAP" in key_mgmt.upper() else "psk"

    tags = {
        "org_id": org_id,
        "site_id": site_id,
        "mac": mac,
        "ap_mac": payload.get("ap_mac", "") or "",
        "ssid": payload.get("ssid", "") or "",
        "band": str(payload.get("band", "") or ""),
        "auth_type": auth_type,
    }

    fields: dict = {
        # Numeric — signal
        "rssi": _to_float(payload.get("rssi")),
        "snr": _to_float(payload.get("snr")),
        "channel": _to_int(payload.get("channel")),
        # Numeric — rates
        "tx_rate": _to_float(payload.get("tx_rate")),
        "rx_rate": _to_float(payload.get("rx_rate")),
        "tx_bps": _to_int(payload.get("tx_bps")),
        "rx_bps": _to_int(payload.get("rx_bps")),
        # Numeric — counters
        "tx_pkts": _to_int(payload.get("tx_pkts")),
        "rx_pkts": _to_int(payload.get("rx_pkts")),
        "tx_bytes": _to_int(payload.get("tx_bytes")),
        "rx_bytes": _to_int(payload.get("rx_bytes")),
        "tx_retries": _to_int(payload.get("tx_retries")),
        "rx_retries": _to_int(payload.get("rx_retries")),
        # Numeric — timing
        "idle_time": _to_float(payload.get("idle_time")),
        "uptime": _to_int(payload.get("uptime")),
        # Boolean stored as 0/1
        "is_guest": 1 if payload.get("is_guest") else 0,
        "dual_band": 1 if payload.get("dual_band") else 0,
        # String identity fields
        "hostname": payload.get("hostname") or "",
        "ip": payload.get("ip") or "",
        "manufacture": payload.get("manufacture") or "",
        "family": payload.get("family") or "",
        "model": payload.get("model") or "",
        "os": payload.get("os") or "",
        "os_version": payload.get("os_version") or "",
        "group": payload.get("group") or "",
        "vlan_id": str(payload.get("vlan_id") or ""),
        "proto": payload.get("proto") or "",
        "key_mgmt": key_mgmt,
        "username": payload.get("username") or "",
        "airespace_ifname": payload.get("airespace_ifname") or "",
        "type": payload.get("type") or "",
    }

    # Drop None values — InfluxDB will omit absent fields gracefully
    fields = {k: v for k, v in fields.items() if v is not None}

    return [
        {
            "measurement": "client_stats",
            "tags": tags,
            "fields": fields,
            "time": timestamp,
        }
    ]


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

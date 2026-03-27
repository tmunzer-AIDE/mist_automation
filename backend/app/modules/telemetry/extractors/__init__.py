"""Metric extractors — dispatch raw WebSocket payloads to device-type-specific extractors."""

from __future__ import annotations

from typing import Any

from app.modules.telemetry.extractors import ap_extractor, gateway_extractor, switch_extractor


def extract_points(payload: dict[str, Any], org_id: str, site_id: str) -> list[dict[str, Any]]:
    """Dispatch payload to the appropriate device-type extractor.

    Returns a list of InfluxDB data points (dicts with measurement, tags, fields, time).
    Returns empty list for unknown device types or unparseable payloads.
    """
    device_type = payload.get("type")

    # AP full-stats messages don't include "type" — detect via model prefix
    if device_type is None and isinstance(payload.get("model"), str) and payload["model"].startswith("AP"):
        device_type = "ap"

    if device_type == "ap":
        return ap_extractor.extract_points(payload, org_id, site_id)
    elif device_type == "switch":
        return switch_extractor.extract_points(payload, org_id, site_id)
    elif device_type == "gateway":
        return gateway_extractor.extract_points(payload, org_id, site_id)

    return []

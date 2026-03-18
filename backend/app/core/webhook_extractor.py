"""
Utilities for extracting monitor-friendly fields from Mist webhook events
and enriching individual events with parent webhook metadata.
"""


def _parse_epoch(value) -> "datetime | None":
    """Convert a Unix epoch (int or float) to a UTC datetime, or None."""
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone

        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def extract_event_fields(event: dict, topic: str, webhook_payload: dict) -> dict:
    """Extract monitor-friendly fields from a single Mist event.

    Returns dict with: event_type, org_name, site_name, device_name, device_mac,
    event_details, event_timestamp.
    """
    return {
        "event_type": event.get("type"),
        "org_name": event.get("org_name") or webhook_payload.get("org_name"),
        "site_name": event.get("site_name"),
        "device_name": event.get("device_name") or event.get("ap") or event.get("switch_name"),
        "device_mac": event.get("mac") or event.get("ap_mac") or event.get("device_mac"),
        "event_details": event.get("text") or event.get("message") or event.get("reason"),
        "event_timestamp": _parse_epoch(event.get("timestamp") or webhook_payload.get("timestamp")),
    }


def enrich_event(event: dict, topic: str, webhook_payload: dict) -> dict:
    """Return a copy of event with topic, org_id, site_id injected from parent webhook."""
    enriched = {**event, "topic": topic}
    for key in ("org_id", "site_id"):
        if key not in enriched and key in webhook_payload:
            enriched[key] = webhook_payload[key]
    return enriched

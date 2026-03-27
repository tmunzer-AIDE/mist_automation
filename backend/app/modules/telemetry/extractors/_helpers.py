"""Shared helpers for metric extractors."""

from __future__ import annotations


def get_timestamp(payload: dict) -> int:
    """Extract epoch timestamp from ``last_seen`` — when the device reported data to Mist.

    Falls back to ``_time`` only if ``last_seen`` is absent.
    """
    raw = payload.get("last_seen") or payload.get("_time") or 0
    return int(raw)

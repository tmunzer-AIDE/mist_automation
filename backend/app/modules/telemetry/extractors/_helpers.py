"""Shared helpers for metric extractors."""

from __future__ import annotations

import time


def get_timestamp(payload: dict) -> int:
    """Extract epoch timestamp from ``last_seen`` — when the device reported data to Mist.

    Falls back to ``_time``, then current time if neither is present.
    """
    raw = payload.get("last_seen") or payload.get("_time") or time.time()
    return int(raw)

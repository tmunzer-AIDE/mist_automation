"""In-memory cache of latest device stats per MAC address.

Provides zero-latency reads for impact analysis and AI chat queries.
Thread-safe via copy-on-read pattern (no locking needed for dict operations
in CPython due to the GIL, but we return copies to prevent external mutation).
"""

from __future__ import annotations

import copy
import time
from typing import Any


class LatestValueCache:
    """Stores the most recent device stats payload per MAC address."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}

    def update(self, mac: str, stats: dict[str, Any]) -> None:
        """Store or replace the latest stats for a device."""
        self._entries[mac] = {
            "stats": stats,
            "updated_at": time.time(),
        }

    def get(self, mac: str) -> dict[str, Any] | None:
        """Get the latest stats for a device, or None if not cached."""
        entry = self._entries.get(mac)
        if entry is None:
            return None
        return copy.deepcopy(entry["stats"])

    def get_fresh(self, mac: str, max_age_seconds: float = 60) -> dict[str, Any] | None:
        """Get stats only if they were updated within max_age_seconds."""
        entry = self._entries.get(mac)
        if entry is None:
            return None
        if time.time() - entry["updated_at"] > max_age_seconds:
            return None
        return copy.deepcopy(entry["stats"])

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all cached stats. Returns a deep copy."""
        return {mac: copy.deepcopy(entry["stats"]) for mac, entry in self._entries.items()}

    def remove(self, mac: str) -> None:
        """Remove a device from the cache."""
        self._entries.pop(mac, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()

    def size(self) -> int:
        """Return the number of cached devices."""
        return len(self._entries)

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

    def get_entry(self, mac: str) -> dict[str, Any] | None:
        """Get the full cache entry (stats + updated_at) for a device, or None."""
        entry = self._entries.get(mac)
        if entry is None:
            return None
        return copy.deepcopy(entry)

    def get_fresh_entry(self, mac: str, max_age_seconds: float = 60) -> dict[str, Any] | None:
        """Get stats with metadata if fresh, or None if stale/missing.

        Unlike get_fresh() which returns only stats, this returns the full
        entry dict including 'updated_at' timestamp.
        """
        entry = self._entries.get(mac)
        if entry is None:
            return None
        if time.time() - entry["updated_at"] > max_age_seconds:
            return None
        return copy.deepcopy(entry)

    def get_all_for_site(self, site_id: str, max_age_seconds: float = 60) -> list[dict[str, Any]]:
        """Get all fresh cached stats for devices at a given site.

        Iterates all entries and filters by site_id found in the stored
        stats payload (Mist WS payloads include 'site_id' field).

        Returns:
            List of fresh stats dicts for devices at the site.
        """
        now = time.time()
        results: list[dict[str, Any]] = []
        for _mac, entry in self._entries.items():
            if now - entry["updated_at"] > max_age_seconds:
                continue
            stats = entry.get("stats", {})
            if stats.get("site_id") == site_id:
                results.append(copy.deepcopy(stats))
        return results

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all cached stats. Returns a deep copy."""
        return {mac: copy.deepcopy(entry["stats"]) for mac, entry in self._entries.items()}

    def get_all_entries(self) -> dict[str, dict[str, Any]]:
        """Get all entries (stats + updated_at) as shallow copies.

        Safe because stats dicts are replaced atomically on update, not mutated in place.
        """
        return {mac: {"stats": entry["stats"], "updated_at": entry["updated_at"]} for mac, entry in self._entries.items()}

    def remove(self, mac: str) -> None:
        """Remove a device from the cache."""
        self._entries.pop(mac, None)

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()

    def prune(self, max_age_seconds: float = 3600) -> int:
        """Remove entries older than max_age_seconds. Returns count of pruned entries."""
        now = time.time()
        stale = [mac for mac, entry in self._entries.items() if now - entry["updated_at"] > max_age_seconds]
        for mac in stale:
            del self._entries[mac]
        return len(stale)

    def size(self) -> int:
        """Return the number of cached devices."""
        return len(self._entries)

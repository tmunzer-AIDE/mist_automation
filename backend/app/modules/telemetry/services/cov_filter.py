"""Change-of-Value (CoV) filter for telemetry metric deduplication.

Tracks last-written values per metric key and determines whether a new
write is needed based on configurable thresholds. Inspired by OPC UA
deadband filtering with guaranteed periodic updates.

Threshold types:
- "exact": write when value differs (for booleans, enums, state changes)
- "always": always write (for monotonic counters like tx_pkts)
- float: write when absolute delta exceeds threshold (for analog metrics)
"""

from __future__ import annotations

import time
from typing import Any


class CoVFilter:
    """Change-of-Value filter with max staleness timeout."""

    def __init__(self, max_staleness_seconds: int = 300) -> None:
        self.max_staleness_seconds = max_staleness_seconds
        # Key: metric_key → (last_fields_dict, last_write_timestamp)
        self._last_written: dict[str, tuple[dict[str, Any], float]] = {}

    def should_write(
        self,
        key: str,
        fields: dict[str, Any],
        thresholds: dict[str, str | float],
    ) -> bool:
        """Determine if fields should be written based on CoV thresholds.

        Args:
            key: Unique identifier (e.g., "mac:measurement:tag_hash")
            fields: Current field values to evaluate
            thresholds: Per-field threshold config ("exact", "always", or float)

        Returns:
            True if a write is warranted.
        """
        prev = self._last_written.get(key)
        if prev is None:
            return True

        prev_fields, prev_time = prev

        # Max staleness — force write if too old
        if time.time() - prev_time > self.max_staleness_seconds:
            return True

        for field_name, value in fields.items():
            threshold = thresholds.get(field_name)
            prev_value = prev_fields.get(field_name)

            # New field not seen before
            if prev_value is None:
                return True

            # No threshold defined — always write
            if threshold is None:
                return True

            if threshold == "always":
                return True

            if threshold == "exact":
                if value != prev_value:
                    return True
            else:
                # Numeric absolute delta
                try:
                    if abs(float(value) - float(prev_value)) > float(threshold):
                        return True
                except (TypeError, ValueError):
                    return True

        return False

    def record_write(self, key: str, fields: dict[str, Any]) -> None:
        """Record that a write was made, updating tracking state."""
        self._last_written[key] = (dict(fields), time.time())

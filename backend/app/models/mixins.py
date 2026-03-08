"""Shared model mixins."""

from datetime import datetime, timezone


class TimestampMixin:
    """Mixin that provides a shared update_timestamp() method."""

    def update_timestamp(self):
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now(timezone.utc)

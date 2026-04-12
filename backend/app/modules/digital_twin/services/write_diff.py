"""Compute a before/after diff between a staged write and the base state."""

from __future__ import annotations

from typing import Any

from app.modules.backup.utils import deep_diff
from app.modules.digital_twin.models import StagedWrite


def build_write_diff(
    write: StagedWrite,
    base_body: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str]:
    """Return (diff_entries, summary) for a single staged write.

    diff_entries shape matches the frontend WriteDiffField:
        { path, change: 'added'|'removed'|'modified', before, after }
    summary is human-readable: "N fields changed" / "new object" / "deleted".
    """
    if write.method == "DELETE":
        return [], "deleted"

    new_body = write.body or {}
    old_body = base_body or {}

    if write.method == "POST":
        entries = [
            {"path": k, "change": "added", "before": None, "after": v}
            for k, v in new_body.items()
        ]
        return entries, "new object"

    # PUT — deep diff
    raw_changes = deep_diff(old_body, new_body)
    entries: list[dict[str, Any]] = []
    for change in raw_changes:
        ctype = change["type"]
        if ctype == "added":
            entries.append(
                {
                    "path": change["path"],
                    "change": "added",
                    "before": None,
                    "after": change["value"],
                }
            )
        elif ctype == "removed":
            entries.append(
                {
                    "path": change["path"],
                    "change": "removed",
                    "before": change["value"],
                    "after": None,
                }
            )
        else:  # modified
            entries.append(
                {
                    "path": change["path"],
                    "change": "modified",
                    "before": change["old"],
                    "after": change["new"],
                }
            )

    count = len(entries)
    summary = f"{count} field changed" if count == 1 else f"{count} fields changed"
    return entries, summary

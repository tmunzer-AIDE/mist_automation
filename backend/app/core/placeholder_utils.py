"""Shared helpers for unresolved template placeholder detection."""

from __future__ import annotations

import re

_PLACEHOLDER_MARKERS: tuple[tuple[str, str], ...] = (("%7b", "%7d"), ("{{", "}}"))
_PLACEHOLDER_FULL_MATCH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\{[^{}]+\}$"),
    re.compile(r"^<[^<>]+>$"),
    re.compile(r"^:[^/]+$"),
)


def is_unresolved_placeholder(value: str | None) -> bool:
    """Return True when a path segment/value appears to be an unresolved placeholder token."""
    if value is None:
        return False

    text = value.strip()
    if not text:
        return False

    lowered = text.lower()
    if any(start in lowered and end in lowered for start, end in _PLACEHOLDER_MARKERS):
        return True
    return any(pattern.match(text) for pattern in _PLACEHOLDER_FULL_MATCH_PATTERNS)


def endpoint_has_unresolved_placeholder(endpoint: str) -> bool:
    """Return True if an endpoint/path string contains unresolved placeholders in any segment."""
    text = endpoint.strip()
    if not text:
        return False

    segments = [segment for segment in text.split("/") if segment]
    return any(is_unresolved_placeholder(segment) for segment in segments)

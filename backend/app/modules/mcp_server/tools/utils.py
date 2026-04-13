"""Shared lightweight validation helpers for MCP tool inputs."""

from uuid import UUID

from app.core.placeholder_utils import endpoint_has_unresolved_placeholder, is_unresolved_placeholder


def is_placeholder(value: str | None) -> bool:
    """Return True when a value looks like an unresolved template/path placeholder."""
    return is_unresolved_placeholder(value)


def endpoint_has_placeholder(endpoint: str) -> bool:
    """Return True if an endpoint string contains unresolved path placeholders."""
    return endpoint_has_unresolved_placeholder(endpoint)


def is_uuid(value: str | None) -> bool:
    """Validate canonical UUID values."""
    if value is None:
        return False
    try:
        UUID(value)
        return True
    except (TypeError, ValueError):
        return False

"""Shared lightweight validation helpers for MCP tool inputs."""

from uuid import UUID


def is_placeholder(value: str | None) -> bool:
    """Return True when a value looks like an unresolved template/path placeholder."""
    if value is None:
        return False

    text = value.strip()
    if not text:
        return False

    lowered = text.lower()
    if "%7b" in lowered and "%7d" in lowered:
        return True
    if "{{" in text or "}}" in text:
        return True
    if text.startswith("{") and text.endswith("}"):
        return True
    if text.startswith("<") and text.endswith(">"):
        return True
    if text.startswith(":"):
        return True
    return False


def endpoint_has_placeholder(endpoint: str) -> bool:
    """Return True if an endpoint string contains unresolved path placeholders."""
    text = endpoint.strip()
    lowered = text.lower()
    if "%7b" in lowered or "%7d" in lowered:
        return True
    if "{" in text or "}" in text:
        return True
    if "<" in text or ">" in text:
        return True
    if "/:" in text:
        return True
    return False


def is_uuid(value: str | None) -> bool:
    """Validate canonical UUID values."""
    if value is None:
        return False
    try:
        UUID(value)
        return True
    except (TypeError, ValueError):
        return False

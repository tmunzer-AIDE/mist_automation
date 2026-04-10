"""
Parse Mist API endpoint URLs into structured metadata.

Extracts object_type, org_id, site_id, and object_id from URLs like:
  /api/v1/orgs/{org_id}/wlans/{wlan_id}
  /api/v1/sites/{site_id}/setting
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SINGLETON_TYPES = {"setting", "info"}

_ORG_PATTERN = re.compile(
    r"^/api/v1/orgs/(?P<org_id>[^/]+)(?:/(?P<resource>[^/]+)(?:/(?P<object_id>[^/]+))?)?$"
)
_SITE_PATTERN = re.compile(
    r"^/api/v1/sites/(?P<site_id>[^/]+)(?:/(?P<resource>[^/]+)(?:/(?P<object_id>[^/]+))?)?$"
)


@dataclass
class ParsedEndpoint:
    """Structured metadata extracted from a Mist API endpoint."""

    method: str
    endpoint: str
    object_type: str | None = None
    org_id: str | None = None
    site_id: str | None = None
    object_id: str | None = None
    scope: str | None = None
    is_singleton: bool = False


def parse_endpoint(method: str, endpoint: str) -> ParsedEndpoint:
    """Parse a Mist API endpoint URL into structured metadata."""
    result = ParsedEndpoint(method=method, endpoint=endpoint)

    m = _SITE_PATTERN.match(endpoint)
    if m:
        result.site_id = m.group("site_id")
        result.scope = "site"
        resource = m.group("resource")
        obj_id = m.group("object_id")

        if resource is None:
            result.object_type = "info"
            result.is_singleton = True
        elif resource in _SINGLETON_TYPES:
            result.object_type = resource
            result.is_singleton = True
        else:
            result.object_type = resource
            result.object_id = obj_id
        return result

    m = _ORG_PATTERN.match(endpoint)
    if m:
        result.org_id = m.group("org_id")
        result.scope = "org"
        resource = m.group("resource")
        obj_id = m.group("object_id")

        if resource is None:
            result.object_type = "info"
            result.is_singleton = True
        elif resource in _SINGLETON_TYPES:
            result.object_type = resource
            result.is_singleton = True
        else:
            result.object_type = resource
            result.object_id = obj_id
        return result

    return result

"""
Parse Mist API endpoint URLs into structured metadata.

Extracts object_type, org_id, site_id, and object_id from URLs like:
  /api/v1/orgs/{org_id}/wlans/{wlan_id}
  /api/v1/sites/{site_id}/setting
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.placeholder_utils import is_unresolved_placeholder

# Valid org-level resource names (collections)
_ORG_RESOURCES: frozenset[str] = frozenset(
    {
        "sites",
        "sitegroups",
        "sitetemplates",
        "templates",
        "wlans",
        "networks",
        "networktemplates",
        "rftemplates",
        "deviceprofiles",
        "aptemplates",
        "gatewaytemplates",
        "aamwprofiles",
        "vpns",
        "psks",
        "pskportals",
        "nacrules",
        "nactags",
        "nacportals",
        "services",
        "servicepolicies",
        "secpolicies",
        "wxrules",
        "wxtags",
        "alarmtemplates",
        "webhooks",
        "mxtunnels",
        "mxclusters",
        "mxedges",
        "avprofiles",
        "idpprofiles",
        "secintelprofiles",
        "ssos",
        "ssoroles",
        "usermacs",
        "assets",
        "assetfilters",
        "evpn_topologies",
        "inventory",
    }
)

# Org-level singletons (no object_id)
_ORG_SINGLETONS: frozenset[str] = frozenset({"settings"})

# Valid site-level resource names (collections)
_SITE_RESOURCES: frozenset[str] = frozenset(
    {
        "wlans",
        "networks",
        "devices",
        "maps",
        "zones",
        "rssizones",
        "psks",
        "assets",
        "beacons",
        "vbeacons",
        "wxrules",
        "wxtags",
        "webhooks",
        "evpn_topologies",
    }
)

# Site-level singletons (no object_id)
_SITE_SINGLETONS: frozenset[str] = frozenset({"settings"})

# Normalization: singular or common LLM mistakes → correct plural form
_NORMALIZATION_MAP: dict[str, str] = {
    "wlan": "wlans",
    "network": "networks",
    "device": "devices",
    "map": "maps",
    "zone": "zones",
    "psk": "psks",
    "beacon": "beacons",
    "asset": "assets",
    "webhook": "webhooks",
    "service": "services",
    "setting": "settings",
    "vpn": "vpns",
    "site": "sites",
    "sitegroup": "sitegroups",
    "site_devices": "devices",
    "site_wlans": "wlans",
    "site_networks": "networks",
    "rftemplate": "rftemplates",
    "networktemplate": "networktemplates",
    "sitetemplate": "sitetemplates",
    "template": "templates",
    "aptemplate": "aptemplates",
    "gatewaytemplate": "gatewaytemplates",
    "deviceprofile": "deviceprofiles",
    "nacrule": "nacrules",
    "nactag": "nactags",
    "nacportal": "nacportals",
    "secpolicy": "secpolicies",
    "servicepolicy": "servicepolicies",
    "wxrule": "wxrules",
    "wxtag": "wxtags",
}

_ORG_PATTERN = re.compile(r"^/api/v1/orgs/(?P<org_id>[^/]+)(?:/(?P<resource>[^/]+)(?:/(?P<object_id>[^/]+))?)?$")
_SITE_PATTERN = re.compile(r"^/api/v1/sites/(?P<site_id>[^/]+)(?:/(?P<resource>[^/]+)(?:/(?P<object_id>[^/]+))?)?$")


def _validate_segments(result: ParsedEndpoint, **segments: str | None) -> bool:
    """Validate parsed path segments do not contain unresolved template placeholders."""
    for segment_name, segment_value in segments.items():
        if is_unresolved_placeholder(segment_value):
            result.error = (
                f"Unresolved path placeholder for '{segment_name}': '{segment_value}'. "
                "Replace placeholders with real UUID values before simulation."
            )
            return False
    return True


def _validate_method_target_shape(
    result: ParsedEndpoint,
    *,
    method: str,
    resource: str,
    object_id: str | None,
    is_singleton: bool,
) -> bool:
    """Validate method/resource/object_id coherence for parsed endpoints."""
    verb = (method or "").upper()

    if is_singleton and object_id:
        result.error = f"Singleton resource '{resource}' does not accept object_id in the endpoint path"
        return False

    if is_singleton and verb != "PUT":
        result.error = f"Singleton resource '{resource}' only supports method 'PUT'"
        return False

    if verb in {"PUT", "DELETE"} and not is_singleton and not object_id:
        result.error = (
            f"Method '{verb}' requires object_id for collection resource '{resource}'. "
            f"Use /.../{resource}/{{object_id}}"
        )
        return False

    if verb == "POST" and object_id:
        result.error = (
            f"Method 'POST' must target a collection endpoint without object_id for resource '{resource}'"
        )
        return False

    return True


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
    error: str | None = None  # set when endpoint is invalid or resource unknown


def parse_endpoint(method: str, endpoint: str) -> ParsedEndpoint:
    """Parse a Mist API endpoint URL into structured metadata."""
    # Strip query/fragment/trailing slash before matching path segments.
    endpoint = endpoint.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    normalized_method = (method or "").upper()
    result = ParsedEndpoint(method=normalized_method, endpoint=endpoint)

    m = _SITE_PATTERN.match(endpoint)
    if m:
        result.site_id = m.group("site_id")
        result.scope = "site"
        resource = m.group("resource")
        obj_id = m.group("object_id")

        if not _validate_segments(result, site_id=result.site_id, resource=resource, object_id=obj_id):
            return result

        if resource is None:
            # /api/v1/sites/{site_id} — site info
            result.object_type = "info"
            result.is_singleton = True
            _validate_method_target_shape(
                result,
                method=result.method,
                resource=result.object_type,
                object_id=obj_id,
                is_singleton=True,
            )
            return result

        # Normalize common LLM mistakes (singular → plural)
        resource = _NORMALIZATION_MAP.get(resource, resource)

        if resource in _SITE_SINGLETONS:
            result.object_type = resource
            result.is_singleton = True
            _validate_method_target_shape(
                result,
                method=result.method,
                resource=result.object_type,
                object_id=obj_id,
                is_singleton=True,
            )
            return result

        if resource in _SITE_RESOURCES:
            result.object_type = resource
            result.object_id = obj_id
            _validate_method_target_shape(
                result,
                method=result.method,
                resource=result.object_type,
                object_id=result.object_id,
                is_singleton=False,
            )
            return result

        # Unknown resource — set error but still populate site_id/scope
        result.error = (
            f"Unknown site resource '{resource}'. "
            f"Valid: {', '.join(sorted(_SITE_RESOURCES | _SITE_SINGLETONS))}"
        )
        return result

    m = _ORG_PATTERN.match(endpoint)
    if m:
        result.org_id = m.group("org_id")
        result.scope = "org"
        resource = m.group("resource")
        obj_id = m.group("object_id")

        if not _validate_segments(result, org_id=result.org_id, resource=resource, object_id=obj_id):
            return result

        if resource is None:
            # /api/v1/orgs/{org_id} — org info
            result.object_type = "data"
            result.is_singleton = True
            _validate_method_target_shape(
                result,
                method=result.method,
                resource=result.object_type,
                object_id=obj_id,
                is_singleton=True,
            )
            return result

        # Normalize common LLM mistakes (singular → plural)
        resource = _NORMALIZATION_MAP.get(resource, resource)

        if resource in _ORG_SINGLETONS:
            result.object_type = resource
            result.is_singleton = True
            _validate_method_target_shape(
                result,
                method=result.method,
                resource=result.object_type,
                object_id=obj_id,
                is_singleton=True,
            )
            return result

        if resource in _ORG_RESOURCES:
            result.object_type = resource
            result.object_id = obj_id
            _validate_method_target_shape(
                result,
                method=result.method,
                resource=result.object_type,
                object_id=result.object_id,
                is_singleton=False,
            )
            return result

        # Unknown resource — set error but still populate org_id/scope
        result.error = (
            f"Unknown org resource '{resource}'. "
            f"Valid: {', '.join(sorted(_ORG_RESOURCES | _ORG_SINGLETONS))}"
        )
        return result

    # Neither pattern matched
    result.error = (
        "Endpoint does not match Mist API pattern "
        "(/api/v1/sites/{site_id}/... or /api/v1/orgs/{org_id}/...)"
    )
    return result

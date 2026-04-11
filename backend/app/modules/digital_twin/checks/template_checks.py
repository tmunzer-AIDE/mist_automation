"""
Template variable checks for the Digital Twin check engine.

TMPL-VAR — Detect unresolved Jinja2 template variables in site settings and device configs.

All functions are pure — no async, no DB access.
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot

# Regex to find Jinja2-style template variables.
# Captures the base variable name from patterns like:
#   {{ var }}, {{ var | default('x') }}, {{ var.nested }}, {{- var }}
_VAR_RE = re.compile(r"\{\{-?\s*(\w+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_vars(value: Any) -> set[str]:
    """Recursively extract {{ variable }} names from a config structure."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(_VAR_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found.update(_extract_vars(v))
    elif isinstance(value, list):
        for item in value:
            found.update(_extract_vars(item))
    return found


# ---------------------------------------------------------------------------
# TMPL-VAR: Unresolved Template Variables
# ---------------------------------------------------------------------------


def check_template_variables(predicted: SiteSnapshot) -> list[CheckResult]:
    """Detect unresolved Jinja2 template variables in site settings and device configs.

    Extracts defined vars from ``site_setting.vars``, then scans:
    - The site_setting dict (excluding the ``vars`` key itself)
    - All device ``port_config``, ``ip_config``, and ``dhcpd_config``

    Returns a single CheckResult: ``error`` if any unresolved vars, ``pass`` otherwise.
    """
    # Extract defined site vars (handle None / missing)
    site_vars: dict[str, Any] = predicted.site_setting.get("vars") or {}
    defined_names: set[str] = set(site_vars.keys())

    # Scan site_setting (excluding "vars" key)
    referenced: set[str] = set()
    for key, value in predicted.site_setting.items():
        if key == "vars":
            continue
        referenced.update(_extract_vars(value))

    # Scan all device configs
    for device in predicted.devices.values():
        referenced.update(_extract_vars(device.port_config))
        referenced.update(_extract_vars(device.ip_config))
        referenced.update(_extract_vars(device.dhcpd_config))

    unresolved = sorted(referenced - defined_names)

    if unresolved:
        details = [f"Variable '{{{{ {var} }}}}' not defined in site vars" for var in unresolved]
        return [
            CheckResult(
                check_id="TMPL-VAR",
                check_name="Unresolved template variables",
                layer=1,
                status="error",
                summary=f"{len(unresolved)} unresolved template variable(s) found",
                details=details,
                affected_sites=[predicted.site_id],
                remediation_hint=f"Define missing variables in site vars: {', '.join(unresolved)}",
            )
        ]

    return [
        CheckResult(
            check_id="TMPL-VAR",
            check_name="Unresolved template variables",
            layer=1,
            status="pass",
            summary="All template variables resolved in site vars.",
        )
    ]

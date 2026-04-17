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

# Jinja2 literals, constants, and common built-in tests/functions that are
# valid without being declared in site_vars. They must NOT be flagged as
# "undefined" when they appear first inside a {{ ... }} expression.
_JINJA_RESERVED: frozenset[str] = frozenset(
    {
        # Literals / constants
        "true",
        "false",
        "none",
        "True",
        "False",
        "None",
        # Common callables / namespaces
        "range",
        "dict",
        "list",
        "lipsum",
        "cycler",
        "joiner",
        "namespace",
        "loop",
        "self",
        "super",
        "varargs",
        "kwargs",
    }
)


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
    - Snapshot networks and WLANs (including template-derived fragments)
    - All device compiled config (falls back to ``port_config``/``ip_config``/``dhcpd_config``)

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

    # Scan snapshot network and WLAN config. These include template-derived
    # fragments when template assignments change via site_info writes.
    for network in predicted.networks.values():
        referenced.update(_extract_vars(network))
    for wlan in predicted.wlans.values():
        referenced.update(_extract_vars(wlan))

    # Scan all device configs
    for device in predicted.devices.values():
        if device.effective_config is not None:
            referenced.update(_extract_vars(device.effective_config))
            continue
        referenced.update(_extract_vars(device.port_config))
        referenced.update(_extract_vars(device.ip_config))
        referenced.update(_extract_vars(device.dhcpd_config))

    # Filter out Jinja2 literals/builtins (true/false/none/range/…) which are
    # valid even though they match the \w+ variable-name regex.
    unresolved = sorted((referenced - defined_names) - _JINJA_RESERVED)

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
                description="Detects Jinja2 {{ variable }} placeholders in device or site config that are not defined in site vars.",
            )
        ]

    return [
        CheckResult(
            check_id="TMPL-VAR",
            check_name="Unresolved template variables",
            layer=1,
            status="pass",
            summary="All template variables resolved in site vars.",
            description="Detects Jinja2 {{ variable }} placeholders in device or site config that are not defined in site vars.",
        )
    ]

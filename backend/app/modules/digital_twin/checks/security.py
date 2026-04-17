"""
Security checks for the Digital Twin check engine.

SEC-GUEST   — Guest SSID without client isolation (Layer 4, warning)
SEC-POLICY  — Security policy changes (Layer 4, warning)
SEC-NAC     — NAC rule changes (Layer 4, warning)

All functions are pure — no async, no DB access.
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot

# ---------------------------------------------------------------------------
# SEC-GUEST: Guest SSID Security
# ---------------------------------------------------------------------------


def _check_guest_ssid(predicted: SiteSnapshot) -> CheckResult:
    """Open WLANs without client isolation are a security risk.

    An SSID is "open" when ``auth.type`` is ``"open"``, ``"none"``, ``""``, or missing.
    Client isolation must be enabled via the ``isolation`` or ``client_isolation`` field.
    """
    issues: list[str] = []
    affected: list[str] = []

    for _wlan_id, wlan in predicted.wlans.items():
        # Skip disabled WLANs
        if not wlan.get("enabled", True):
            continue

        ssid = wlan.get("ssid", "")
        auth: dict[str, Any] = wlan.get("auth") or {}
        auth_type = auth.get("type", "")

        # Only check open/unauthenticated WLANs
        if auth_type not in ("open", "none", ""):
            continue

        # Check for client isolation
        isolated = wlan.get("isolation") or wlan.get("client_isolation")
        if not isolated:
            issues.append(f"SSID '{ssid}' is open without client isolation")
            if ssid and ssid not in affected:
                affected.append(ssid)

    if issues:
        return CheckResult(
            check_id="SEC-GUEST",
            check_name="Guest SSID Security",
            layer=4,
            status="warning",
            summary=f"{len(issues)} open SSID(s) without client isolation",
            details=issues,
            affected_objects=affected,
            affected_sites=[predicted.site_id],
            remediation_hint="Enable client isolation on open/guest SSIDs to prevent lateral traffic.",
            description="Flags open (unauthenticated) SSIDs that do not have client isolation enabled, allowing lateral traffic between clients.",
        )

    return CheckResult(
        check_id="SEC-GUEST",
        check_name="Guest SSID Security",
        layer=4,
        status="pass",
        summary="All open SSIDs have client isolation enabled.",
        description="Flags open (unauthenticated) SSIDs that do not have client isolation enabled, allowing lateral traffic between clients.",
    )


# ---------------------------------------------------------------------------
# SEC-POLICY: Security Policy Changes
# ---------------------------------------------------------------------------


def _index_by_name(policies: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a dict keyed by policy ``name`` for comparison."""
    result: dict[str, dict[str, Any]] = {}
    for policy in policies:
        name = policy.get("name", "")
        if name:
            result[name] = policy
    return result


def _check_security_policies(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Compare security policies between baseline and predicted snapshots."""
    base_policies: list[dict[str, Any]] = baseline.site_setting.get("secpolicies", []) or []
    pred_policies: list[dict[str, Any]] = predicted.site_setting.get("secpolicies", []) or []

    base_map = _index_by_name(base_policies)
    pred_map = _index_by_name(pred_policies)

    base_names = set(base_map.keys())
    pred_names = set(pred_map.keys())

    added = sorted(pred_names - base_names)
    removed = sorted(base_names - pred_names)
    modified: list[str] = []
    for name in sorted(base_names & pred_names):
        if base_map[name] != pred_map[name]:
            modified.append(name)

    if added or removed or modified:
        details: list[str] = []
        if added:
            details.append(f"Added: {', '.join(added)}")
        if removed:
            details.append(f"Removed: {', '.join(removed)}")
        if modified:
            details.append(f"Modified: {', '.join(modified)}")

        return CheckResult(
            check_id="SEC-POLICY",
            check_name="Security Policy Changes",
            layer=4,
            status="warning",
            summary=f"Security policy changes detected: {len(added)} added, {len(removed)} removed, {len(modified)} modified",
            details=details,
            affected_sites=[predicted.site_id],
            remediation_hint="Review security policy changes to ensure they align with organizational requirements.",
            description="Reports additions, removals, or modifications to security policies between baseline and predicted state.",
        )

    return CheckResult(
        check_id="SEC-POLICY",
        check_name="Security Policy Changes",
        layer=4,
        status="pass",
        summary="No security policy changes detected.",
        description="Reports additions, removals, or modifications to security policies between baseline and predicted state.",
    )


# ---------------------------------------------------------------------------
# SEC-NAC: NAC Rule Changes
# ---------------------------------------------------------------------------


def _canonicalize_for_compare(value: Any) -> Any:
    """Recursively produce an order-insensitive canonical form of a value.

    - dicts -> sort keys, recurse
    - lists -> recurse, then sort (by canonical JSON of each element) so that
      reordered match-conditions / tag lists inside a rule don't produce
      a false-positive diff
    - scalars -> returned as-is (json.dumps(default=str) handles non-JSON-safe)
    """
    if isinstance(value, dict):
        return {k: _canonicalize_for_compare(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, list):
        canonicalized = [_canonicalize_for_compare(v) for v in value]
        try:
            return sorted(canonicalized, key=lambda v: json.dumps(v, sort_keys=True, default=str))
        except (TypeError, ValueError):
            return canonicalized
    return value


def _normalize_nac_rule(rule: dict[str, Any]) -> str:
    """Serialize a NAC rule into a stable, order-insensitive string key.

    Dict keys AND list element order are normalized so semantically identical
    rules (e.g. same match conditions in a different order after a backup
    round-trip) collapse to the same key.
    """
    try:
        return json.dumps(_canonicalize_for_compare(rule), sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(rule)


def _check_nac_rules(baseline: SiteSnapshot, predicted: SiteSnapshot) -> CheckResult:
    """Compare NAC rules between baseline and predicted snapshots."""
    base_rules: list[dict[str, Any]] = baseline.site_setting.get("nacrules", []) or []
    pred_rules: list[dict[str, Any]] = predicted.site_setting.get("nacrules", []) or []

    # Compare by content (order-insensitive) so a backup round-trip returning
    # the same rules in a different order doesn't produce a false-positive.
    base_keys = {_normalize_nac_rule(r) for r in base_rules if isinstance(r, dict)}
    pred_keys = {_normalize_nac_rule(r) for r in pred_rules if isinstance(r, dict)}

    if base_keys != pred_keys:
        base_count = len(base_rules)
        pred_count = len(pred_rules)
        added = len(pred_keys - base_keys)
        removed = len(base_keys - pred_keys)
        details: list[str] = [f"NAC rules changed from {base_count} to {pred_count} ({added} added, {removed} removed)"]

        return CheckResult(
            check_id="SEC-NAC",
            check_name="NAC Rule Changes",
            layer=4,
            status="warning",
            summary=f"NAC rules changed ({added} added, {removed} removed)",
            details=details,
            affected_sites=[predicted.site_id],
            remediation_hint="Review NAC rule changes to ensure network access control remains correct.",
            description="Reports changes to NAC rules between baseline and predicted state.",
        )

    return CheckResult(
        check_id="SEC-NAC",
        check_name="NAC Rule Changes",
        layer=4,
        status="pass",
        summary="No NAC rule changes detected.",
        description="Reports changes to NAC rules between baseline and predicted state.",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def check_security(baseline: SiteSnapshot, predicted: SiteSnapshot) -> list[CheckResult]:
    """Run all security checks and return aggregated results.

    Args:
        baseline: Site snapshot before changes.
        predicted: Site snapshot after applying staged writes.

    Returns:
        List of CheckResult for SEC-GUEST, SEC-POLICY, SEC-NAC.
    """
    results: list[CheckResult] = []
    results.append(_check_guest_ssid(predicted))
    results.append(_check_security_policies(baseline, predicted))
    results.append(_check_nac_rules(baseline, predicted))
    return results

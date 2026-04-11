"""
Layer 4 security policy checks for the Digital Twin module.

All functions are pure — no async, no DB access.
Each returns a CheckResult with check_id, status, summary, details, and remediation_hint.
"""

from __future__ import annotations

from app.modules.digital_twin.models import CheckResult

# RFC1918 private ranges
_RFC1918_RANGES = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_guest_candidate(wlan: dict) -> bool:
    """Return True if the WLAN should be checked for guest security (name contains 'guest' or auth is open)."""
    ssid = wlan.get("ssid", "") or wlan.get("name", "")
    if "guest" in ssid.lower():
        return True
    auth = wlan.get("auth", {})
    if isinstance(auth, dict) and auth.get("type") == "open":
        return True
    return False


def _has_client_isolation(wlan: dict) -> bool:
    """Return True if client isolation is enabled on the WLAN."""
    return bool(wlan.get("isolation") or wlan.get("client_isolation"))


def _has_rfc1918_acl(wlan: dict) -> bool:
    """Return True if the WLAN has an ACL/policy blocking RFC1918 ranges."""
    return bool(wlan.get("block_rfc1918"))


# ---------------------------------------------------------------------------
# L4-01: Guest SSID security violation
# ---------------------------------------------------------------------------


def check_guest_ssid_security(all_wlans: list[dict]) -> CheckResult:
    """
    Check guest SSIDs (by name or open auth) for missing client isolation
    and missing ACL blocking RFC1918 ranges.
    """
    violations: list[str] = []
    affected_objects: list[str] = []
    affected_sites: list[str] = []

    for wlan in all_wlans:
        if not _is_guest_candidate(wlan):
            continue
        ssid = wlan.get("ssid") or wlan.get("name", "<unnamed>")
        if _has_client_isolation(wlan) or _has_rfc1918_acl(wlan):
            continue
        violations.append(f"WLAN '{ssid}' is a guest/open SSID without client isolation or RFC1918 ACL blocking")
        affected_objects.append(ssid)
        site_id = wlan.get("_site_id")
        if site_id and site_id not in affected_sites:
            affected_sites.append(site_id)

    if violations:
        return CheckResult(
            check_id="L4-01",
            check_name="Guest SSID security violation",
            layer=4,
            status="critical",
            summary=f"{len(violations)} guest/open SSID(s) lack client isolation and RFC1918 ACL protection",
            details=violations,
            affected_objects=affected_objects,
            affected_sites=affected_sites,
            remediation_hint=(
                "Enable 'client_isolation' on guest WLANs or add an ACL policy blocking "
                f"RFC1918 ranges ({', '.join(_RFC1918_RANGES)})"
            ),
        )

    return CheckResult(
        check_id="L4-01",
        check_name="Guest SSID security violation",
        layer=4,
        status="pass",
        summary="All guest/open SSIDs have client isolation or RFC1918 ACL protection",
    )


# ---------------------------------------------------------------------------
# L4-02: NAC auth server dependency
# ---------------------------------------------------------------------------


def check_nac_auth_server_dependency(
    nac_rules: list[dict],
    auth_servers: list[dict],
) -> CheckResult:
    """
    Check that every auth server referenced by a NAC rule still exists in the
    predicted auth_servers list.
    """
    if not nac_rules:
        return CheckResult(
            check_id="L4-02",
            check_name="NAC auth server dependency",
            layer=4,
            status="skipped",
            summary="No NAC rules to validate",
        )

    # Build lookup sets from available auth servers (by id and by name)
    server_ids: set[str] = set()
    server_names: set[str] = set()
    for srv in auth_servers:
        if srv_id := srv.get("id"):
            server_ids.add(str(srv_id))
        if srv_name := srv.get("name"):
            server_names.add(srv_name)

    missing: list[str] = []
    affected_objects: list[str] = []

    for rule in nac_rules:
        rule_name = rule.get("name", "<unnamed>")

        # Single server reference by ID
        if ref_id := rule.get("auth_server_id"):
            ref_id = str(ref_id)
            if ref_id not in server_ids:
                missing.append(f"NAC rule '{rule_name}' references missing auth server id '{ref_id}'")
                affected_objects.append(rule_name)

        # List of server references (by ID or name)
        for ref in rule.get("auth_servers", []):
            ref = str(ref)
            if ref not in server_ids and ref not in server_names:
                missing.append(f"NAC rule '{rule_name}' references missing auth server '{ref}'")
                if rule_name not in affected_objects:
                    affected_objects.append(rule_name)

    if missing:
        return CheckResult(
            check_id="L4-02",
            check_name="NAC auth server dependency",
            layer=4,
            status="critical",
            summary=f"{len(missing)} NAC rule(s) reference auth server(s) that no longer exist",
            details=missing,
            affected_objects=affected_objects,
            remediation_hint="Ensure all referenced auth servers exist or update NAC rules to use existing servers",
        )

    return CheckResult(
        check_id="L4-02",
        check_name="NAC auth server dependency",
        layer=4,
        status="pass",
        summary="All NAC rules reference valid auth servers",
    )


# ---------------------------------------------------------------------------
# L4-03: NAC VLAN assignment conflict
# ---------------------------------------------------------------------------


def _rule_vlan(rule: dict) -> str | None:
    """Extract VLAN assignment from a NAC rule (vlan or vlan_id field)."""
    vlan = rule.get("vlan") or rule.get("vlan_id")
    return str(vlan) if vlan is not None else None


def _matching_key(rule: dict) -> str | None:
    """Return a canonical string key from the rule's matching criteria, or None if absent."""
    matching = rule.get("matching")
    if not matching:
        return None
    if isinstance(matching, dict):
        # Sort for determinism
        return str(sorted(matching.items()))
    return str(matching)


def check_nac_vlan_conflict(nac_rules: list[dict]) -> CheckResult:
    """
    Detect pairs of NAC rules with overlapping match criteria that assign
    different VLANs to the same client.
    """
    if len(nac_rules) < 2:
        return CheckResult(
            check_id="L4-03",
            check_name="NAC VLAN assignment conflict",
            layer=4,
            status="skipped",
            summary="Not enough NAC rules to check for VLAN conflicts",
        )

    conflicts: list[str] = []
    affected_objects: list[str] = []

    # Group rules by matching criteria
    by_criteria: dict[str, list[dict]] = {}
    for rule in nac_rules:
        key = _matching_key(rule)
        if key is None:
            continue
        by_criteria.setdefault(key, []).append(rule)

    for _key, rules in by_criteria.items():
        if len(rules) < 2:
            continue
        # Check all pairs within the same criteria group
        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                vlan_i = _rule_vlan(rules[i])
                vlan_j = _rule_vlan(rules[j])
                if vlan_i is None or vlan_j is None:
                    continue
                if vlan_i != vlan_j:
                    name_i = rules[i].get("name", f"rule-{i}")
                    name_j = rules[j].get("name", f"rule-{j}")
                    conflicts.append(
                        f"Rules '{name_i}' (VLAN {vlan_i}) and '{name_j}' (VLAN {vlan_j}) "
                        f"have identical match criteria but assign different VLANs"
                    )
                    for name in (name_i, name_j):
                        if name not in affected_objects:
                            affected_objects.append(name)

    if conflicts:
        return CheckResult(
            check_id="L4-03",
            check_name="NAC VLAN assignment conflict",
            layer=4,
            status="error",
            summary=f"{len(conflicts)} conflicting VLAN assignment(s) found in NAC rules",
            details=conflicts,
            affected_objects=affected_objects,
            remediation_hint="Ensure each unique match criteria maps to a single VLAN across all NAC rules",
        )

    return CheckResult(
        check_id="L4-03",
        check_name="NAC VLAN assignment conflict",
        layer=4,
        status="pass",
        summary="No conflicting VLAN assignments found in NAC rules",
    )


# ---------------------------------------------------------------------------
# L4-04: Unreachable firewall destination
# ---------------------------------------------------------------------------


def check_unreachable_destination(
    security_policies: list[dict],
    networks: list[dict],
    services: list[dict],
) -> CheckResult:
    """
    Check that every network/service reference in a security policy actually
    exists in the predicted state.
    """
    if not security_policies:
        return CheckResult(
            check_id="L4-04",
            check_name="Unreachable firewall destination",
            layer=4,
            status="skipped",
            summary="No security policies to validate",
        )

    # Build lookup sets (by name and by id)
    network_names: set[str] = {n["name"] for n in networks if "name" in n}
    network_ids: set[str] = {str(n["id"]) for n in networks if "id" in n}
    service_names: set[str] = {s["name"] for s in services if "name" in s}
    service_ids: set[str] = {str(s["id"]) for s in services if "id" in s}

    missing: list[str] = []
    affected_objects: list[str] = []

    for policy in security_policies:
        policy_name = policy.get("name", "<unnamed>")
        found_issue = False

        # Check src_tags and dst_tags (network name references)
        for tag_field in ("src_tags", "dst_tags"):
            for tag in policy.get(tag_field, []):
                tag = str(tag)
                if tag not in network_names and tag not in network_ids:
                    missing.append(f"Policy '{policy_name}' references unknown network '{tag}' in '{tag_field}'")
                    found_issue = True

        # Check service/application references
        for svc_ref in policy.get("services", []):
            svc_ref = str(svc_ref)
            if svc_ref not in service_names and svc_ref not in service_ids:
                missing.append(f"Policy '{policy_name}' references unknown service '{svc_ref}'")
                found_issue = True

        if found_issue and policy_name not in affected_objects:
            affected_objects.append(policy_name)

    if missing:
        return CheckResult(
            check_id="L4-04",
            check_name="Unreachable firewall destination",
            layer=4,
            status="error",
            summary=f"{len(missing)} security policy reference(s) point to non-existent network/service objects",
            details=missing,
            affected_objects=affected_objects,
            remediation_hint=(
                "Create the missing network or service objects, or update policies to reference existing objects"
            ),
        )

    return CheckResult(
        check_id="L4-04",
        check_name="Unreachable firewall destination",
        layer=4,
        status="pass",
        summary="All security policy references resolve to known network and service objects",
    )


# ---------------------------------------------------------------------------
# L4-05: Service policy object reference
# ---------------------------------------------------------------------------


def check_service_policy_references(
    service_policies: list[dict],
    services: list[dict],
) -> CheckResult:
    """
    Check that every service referenced by a service policy actually exists
    in the predicted services list.
    """
    if not service_policies:
        return CheckResult(
            check_id="L4-05",
            check_name="Service policy object reference",
            layer=4,
            status="skipped",
            summary="No service policies to validate",
        )

    service_names: set[str] = {s["name"] for s in services if "name" in s}
    service_ids: set[str] = {str(s["id"]) for s in services if "id" in s}

    missing: list[str] = []
    affected_objects: list[str] = []

    for policy in service_policies:
        policy_name = policy.get("name", "<unnamed>")
        found_issue = False

        for svc_ref in policy.get("services", []):
            svc_ref = str(svc_ref)
            if svc_ref not in service_names and svc_ref not in service_ids:
                missing.append(f"Service policy '{policy_name}' references unknown service '{svc_ref}'")
                found_issue = True

        for svc_id_ref in policy.get("service_ids", []):
            svc_id_ref = str(svc_id_ref)
            if svc_id_ref not in service_ids and svc_id_ref not in service_names:
                missing.append(f"Service policy '{policy_name}' references unknown service id '{svc_id_ref}'")
                found_issue = True

        if found_issue and policy_name not in affected_objects:
            affected_objects.append(policy_name)

    if missing:
        return CheckResult(
            check_id="L4-05",
            check_name="Service policy object reference",
            layer=4,
            status="error",
            summary=f"{len(missing)} service policy reference(s) point to non-existent service objects",
            details=missing,
            affected_objects=affected_objects,
            remediation_hint="Create the missing service objects or update policies to reference existing services",
        )

    return CheckResult(
        check_id="L4-05",
        check_name="Service policy object reference",
        layer=4,
        status="pass",
        summary="All service policy references resolve to known service objects",
    )


# ---------------------------------------------------------------------------
# L4-06: Firewall rule shadow
# ---------------------------------------------------------------------------


def _is_any_any(policy: dict) -> bool:
    """Return True if the policy matches any source and any destination (shadow trigger)."""
    src = policy.get("src", "")
    dst = policy.get("dst", "")
    src_tags = policy.get("src_tags", [])
    dst_tags = policy.get("dst_tags", [])
    # A rule is "any/any" if src and dst are both "any" and no specific tags are set
    return str(src).lower() == "any" and str(dst).lower() == "any" and not src_tags and not dst_tags


def check_firewall_rule_shadow(security_policies: list[dict]) -> CheckResult:
    """
    Detect firewall rules that will never match because a broader preceding rule
    already covers the same traffic.

    Heuristic: if rule N has src=any and dst=any, all rules after N are shadowed.
    """
    if len(security_policies) < 2:
        return CheckResult(
            check_id="L4-06",
            check_name="Firewall rule shadow",
            layer=4,
            status="skipped",
            summary="Not enough security policies to check for rule shadowing",
        )

    shadowed: list[str] = []
    affected_objects: list[str] = []
    shadow_start: int | None = None

    for idx, policy in enumerate(security_policies):
        if shadow_start is not None:
            # This rule is shadowed by the any/any rule at shadow_start
            rule_name = policy.get("name", f"rule-{idx}")
            shadower = security_policies[shadow_start].get("name", f"rule-{shadow_start}")
            shadowed.append(f"Rule '{rule_name}' is shadowed by '{shadower}' (any/any rule at position {shadow_start})")
            affected_objects.append(rule_name)
        elif _is_any_any(policy):
            # Mark this as the first any/any rule — subsequent rules are shadowed
            shadow_start = idx

    if shadowed:
        return CheckResult(
            check_id="L4-06",
            check_name="Firewall rule shadow",
            layer=4,
            status="warning",
            summary=f"{len(shadowed)} firewall rule(s) are shadowed and will never match",
            details=shadowed,
            affected_objects=affected_objects,
            remediation_hint=(
                "Move more-specific rules above the broad 'any/any' rule, or remove the unreachable rules"
            ),
        )

    return CheckResult(
        check_id="L4-06",
        check_name="Firewall rule shadow",
        layer=4,
        status="pass",
        summary="No shadowed firewall rules detected",
    )

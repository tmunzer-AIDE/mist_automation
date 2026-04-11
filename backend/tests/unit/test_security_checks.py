"""
Unit tests for Layer 4 security policy checks.
TDD: tests written before implementation.
"""

from app.modules.digital_twin.services.security_checks import (
    check_firewall_rule_shadow,
    check_guest_ssid_security,
    check_nac_auth_server_dependency,
    check_nac_vlan_conflict,
    check_service_policy_references,
    check_unreachable_destination,
)

# ---------------------------------------------------------------------------
# L4-01: Guest SSID security violation
# ---------------------------------------------------------------------------


class TestL4_01:
    def test_guest_ssid_no_isolation_no_acl_is_critical(self):
        wlans = [{"ssid": "Guest-WiFi", "isolation": False, "_site_id": "site-a"}]
        result = check_guest_ssid_security(wlans)
        assert result.check_id == "L4-01"
        assert result.status == "critical"
        assert len(result.affected_objects) >= 1

    def test_guest_ssid_with_client_isolation_passes(self):
        wlans = [{"ssid": "Guest-WiFi", "client_isolation": True, "_site_id": "site-a"}]
        result = check_guest_ssid_security(wlans)
        assert result.check_id == "L4-01"
        assert result.status == "pass"

    def test_open_auth_no_isolation_is_critical(self):
        wlans = [{"ssid": "OpenNet", "auth": {"type": "open"}, "_site_id": "site-b"}]
        result = check_guest_ssid_security(wlans)
        assert result.status == "critical"

    def test_open_auth_with_isolation_passes(self):
        wlans = [{"ssid": "OpenNet", "auth": {"type": "open"}, "isolation": True, "_site_id": "site-b"}]
        result = check_guest_ssid_security(wlans)
        assert result.status == "pass"

    def test_guest_ssid_with_acl_rfc1918_passes(self):
        wlans = [
            {
                "ssid": "guest",
                "isolation": False,
                "acl_policies": ["block-rfc1918"],
                "block_rfc1918": True,
                "_site_id": "site-a",
            }
        ]
        result = check_guest_ssid_security(wlans)
        assert result.status == "pass"

    def test_non_guest_ssid_not_flagged(self):
        wlans = [{"ssid": "CorpSSID", "auth": {"type": "psk"}, "_site_id": "site-a"}]
        result = check_guest_ssid_security(wlans)
        assert result.status == "pass"

    def test_empty_wlans_passes(self):
        result = check_guest_ssid_security([])
        assert result.status == "pass"

    def test_affected_sites_populated(self):
        wlans = [{"ssid": "guest-vip", "isolation": False, "_site_id": "site-x"}]
        result = check_guest_ssid_security(wlans)
        assert result.status == "critical"
        assert "site-x" in result.affected_sites


# ---------------------------------------------------------------------------
# L4-02: NAC auth server dependency
# ---------------------------------------------------------------------------


class TestL4_02:
    def test_missing_auth_server_is_critical(self):
        nac_rules = [{"name": "Rule1", "auth_server_id": "server-missing"}]
        auth_servers = [{"id": "server-other", "name": "OtherServer"}]
        result = check_nac_auth_server_dependency(nac_rules, auth_servers)
        assert result.check_id == "L4-02"
        assert result.status == "critical"
        assert len(result.affected_objects) >= 1

    def test_all_auth_servers_present_passes(self):
        nac_rules = [{"name": "Rule1", "auth_server_id": "server-abc"}]
        auth_servers = [{"id": "server-abc", "name": "RadiusServer"}]
        result = check_nac_auth_server_dependency(nac_rules, auth_servers)
        assert result.status == "pass"

    def test_no_nac_rules_skipped(self):
        result = check_nac_auth_server_dependency([], [])
        assert result.check_id == "L4-02"
        assert result.status == "skipped"

    def test_auth_servers_list_field_missing_server_is_critical(self):
        nac_rules = [{"name": "Rule2", "auth_servers": ["server-gone", "server-ok"]}]
        auth_servers = [{"id": "server-ok", "name": "GoodServer"}]
        result = check_nac_auth_server_dependency(nac_rules, auth_servers)
        assert result.status == "critical"

    def test_auth_servers_list_field_all_present_passes(self):
        nac_rules = [{"name": "Rule2", "auth_servers": ["server-a", "server-b"]}]
        auth_servers = [{"id": "server-a", "name": "A"}, {"id": "server-b", "name": "B"}]
        result = check_nac_auth_server_dependency(nac_rules, auth_servers)
        assert result.status == "pass"

    def test_rule_without_auth_server_reference_skipped(self):
        nac_rules = [{"name": "RuleNoAuth", "action": "allow"}]
        auth_servers = []
        result = check_nac_auth_server_dependency(nac_rules, auth_servers)
        assert result.status in ("pass", "skipped")


# ---------------------------------------------------------------------------
# L4-03: NAC VLAN assignment conflict
# ---------------------------------------------------------------------------


class TestL4_03:
    def test_overlapping_criteria_different_vlans_is_error(self):
        nac_rules = [
            {"name": "Rule1", "matching": {"radius_group": "employees"}, "vlan": "100"},
            {"name": "Rule2", "matching": {"radius_group": "employees"}, "vlan": "200"},
        ]
        result = check_nac_vlan_conflict(nac_rules)
        assert result.check_id == "L4-03"
        assert result.status == "error"
        assert len(result.affected_objects) >= 2

    def test_overlapping_criteria_same_vlan_passes(self):
        nac_rules = [
            {"name": "Rule1", "matching": {"radius_group": "employees"}, "vlan": "100"},
            {"name": "Rule2", "matching": {"radius_group": "employees"}, "vlan": "100"},
        ]
        result = check_nac_vlan_conflict(nac_rules)
        assert result.status == "pass"

    def test_different_criteria_no_conflict(self):
        nac_rules = [
            {"name": "Rule1", "matching": {"radius_group": "employees"}, "vlan": "100"},
            {"name": "Rule2", "matching": {"radius_group": "contractors"}, "vlan": "200"},
        ]
        result = check_nac_vlan_conflict(nac_rules)
        assert result.status == "pass"

    def test_no_nac_rules_skipped(self):
        result = check_nac_vlan_conflict([])
        assert result.check_id == "L4-03"
        assert result.status == "skipped"

    def test_single_rule_skipped(self):
        nac_rules = [{"name": "Rule1", "matching": {"radius_group": "employees"}, "vlan": "100"}]
        result = check_nac_vlan_conflict(nac_rules)
        assert result.status == "skipped"

    def test_vlan_id_field_also_checked(self):
        nac_rules = [
            {"name": "Rule1", "matching": {"radius_group": "staff"}, "vlan_id": 10},
            {"name": "Rule2", "matching": {"radius_group": "staff"}, "vlan_id": 20},
        ]
        result = check_nac_vlan_conflict(nac_rules)
        assert result.status == "error"


# ---------------------------------------------------------------------------
# L4-04: Unreachable firewall destination
# ---------------------------------------------------------------------------


class TestL4_04:
    def test_policy_references_missing_network_is_error(self):
        security_policies = [{"name": "Policy1", "src_tags": ["net-known"], "dst_tags": ["net-gone"]}]
        networks = [{"name": "net-known"}]
        services = []
        result = check_unreachable_destination(security_policies, networks, services)
        assert result.check_id == "L4-04"
        assert result.status == "error"
        assert len(result.affected_objects) >= 1

    def test_policy_all_references_exist_passes(self):
        security_policies = [{"name": "Policy1", "src_tags": ["net-a"], "dst_tags": ["net-b"]}]
        networks = [{"name": "net-a"}, {"name": "net-b"}]
        services = []
        result = check_unreachable_destination(security_policies, networks, services)
        assert result.status == "pass"

    def test_policy_references_missing_service_is_error(self):
        security_policies = [{"name": "Policy1", "services": ["svc-gone"]}]
        networks = []
        services = [{"name": "svc-present"}]
        result = check_unreachable_destination(security_policies, networks, services)
        assert result.status == "error"

    def test_no_security_policies_skipped(self):
        result = check_unreachable_destination([], [], [])
        assert result.check_id == "L4-04"
        assert result.status == "skipped"

    def test_policy_with_no_tags_or_services_passes(self):
        security_policies = [{"name": "Policy1", "action": "allow"}]
        networks = []
        services = []
        result = check_unreachable_destination(security_policies, networks, services)
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L4-05: Service policy object reference
# ---------------------------------------------------------------------------


class TestL4_05:
    def test_service_policy_missing_service_is_error(self):
        service_policies = [{"name": "AppPolicy1", "services": ["app-gone"]}]
        services = [{"name": "app-present"}]
        result = check_service_policy_references(service_policies, services)
        assert result.check_id == "L4-05"
        assert result.status == "error"
        assert len(result.affected_objects) >= 1

    def test_service_policy_all_services_exist_passes(self):
        service_policies = [{"name": "AppPolicy1", "services": ["app-http", "app-dns"]}]
        services = [{"name": "app-http"}, {"name": "app-dns"}]
        result = check_service_policy_references(service_policies, services)
        assert result.status == "pass"

    def test_no_service_policies_skipped(self):
        result = check_service_policy_references([], [])
        assert result.check_id == "L4-05"
        assert result.status == "skipped"

    def test_service_policy_with_service_id_field(self):
        service_policies = [{"name": "AppPolicy2", "service_ids": ["svc-id-gone"]}]
        services = [{"id": "svc-id-present", "name": "Present"}]
        result = check_service_policy_references(service_policies, services)
        assert result.status == "error"

    def test_service_policy_all_ids_present_passes(self):
        service_policies = [{"name": "AppPolicy2", "service_ids": ["svc-id-a"]}]
        services = [{"id": "svc-id-a", "name": "ServiceA"}]
        result = check_service_policy_references(service_policies, services)
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L4-06: Firewall rule shadow
# ---------------------------------------------------------------------------


class TestL4_06:
    def test_any_any_rule_shadows_subsequent_rules_is_warning(self):
        security_policies = [
            {"name": "AllowAll", "src": "any", "dst": "any", "action": "allow"},
            {"name": "BlockInternal", "src": "10.0.0.0/8", "dst": "any", "action": "deny"},
        ]
        result = check_firewall_rule_shadow(security_policies)
        assert result.check_id == "L4-06"
        assert result.status == "warning"
        assert len(result.affected_objects) >= 1

    def test_no_shadow_when_specific_rules_first(self):
        security_policies = [
            {"name": "BlockInternal", "src": "10.0.0.0/8", "dst": "any", "action": "deny"},
            {"name": "AllowAll", "src": "any", "dst": "any", "action": "allow"},
        ]
        result = check_firewall_rule_shadow(security_policies)
        assert result.check_id == "L4-06"
        assert result.status == "pass"

    def test_no_policies_skipped(self):
        result = check_firewall_rule_shadow([])
        assert result.check_id == "L4-06"
        assert result.status == "skipped"

    def test_single_policy_skipped(self):
        security_policies = [{"name": "Rule1", "src": "any", "dst": "any", "action": "allow"}]
        result = check_firewall_rule_shadow(security_policies)
        assert result.status == "skipped"

    def test_multiple_any_any_all_subsequent_shadowed(self):
        security_policies = [
            {"name": "BigAllow", "src": "any", "dst": "any", "action": "allow"},
            {"name": "Rule2", "src": "192.168.0.0/16", "dst": "any", "action": "deny"},
            {"name": "Rule3", "src": "172.16.0.0/12", "dst": "10.0.0.0/8", "action": "deny"},
        ]
        result = check_firewall_rule_shadow(security_policies)
        assert result.status == "warning"
        # Both Rule2 and Rule3 should be listed as shadowed
        assert len(result.affected_objects) >= 2

    def test_any_any_both_directions_shadowed(self):
        security_policies = [
            {"name": "R1", "src": "any", "dst": "any", "action": "allow"},
            {"name": "R2", "src": "any", "dst": "any", "action": "deny"},
        ]
        result = check_firewall_rule_shadow(security_policies)
        assert result.status == "warning"

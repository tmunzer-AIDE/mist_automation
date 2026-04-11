"""
Unit tests for security snapshot checks (SEC-GUEST, SEC-POLICY, SEC-NAC).

These checks compare baseline vs predicted SiteSnapshots.
"""

from __future__ import annotations

from app.modules.digital_twin.checks.security import check_security
from app.modules.digital_twin.services.site_snapshot import SiteSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap(
    wlans=None,
    site_setting=None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting=site_setting or {},
        networks={},
        wlans=wlans or {},
        devices={},
        port_usages={},
        lldp_neighbors={},
        port_status={},
        ap_clients={},
        port_devices={},
        ospf_peers={},
        bgp_peers={},
    )


def _get_result(results, check_id):
    """Extract a specific check result by check_id."""
    for r in results:
        if r.check_id == check_id:
            return r
    return None


# ---------------------------------------------------------------------------
# TestSecGuest
# ---------------------------------------------------------------------------


class TestSecGuest:
    def test_open_ssid_without_isolation_warning(self):
        """An open SSID without client isolation should produce a warning."""
        baseline = _snap()
        predicted = _snap(
            wlans={
                "wlan-1": {
                    "ssid": "Guest-WiFi",
                    "enabled": True,
                    "auth": {"type": "open"},
                },
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-GUEST")
        assert r is not None
        assert r.status == "warning"
        assert len(r.details) == 1
        assert "Guest-WiFi" in r.details[0]
        assert "open without client isolation" in r.details[0]

    def test_open_ssid_with_isolation_passes(self):
        """An open SSID with client isolation enabled should pass."""
        baseline = _snap()
        predicted = _snap(
            wlans={
                "wlan-1": {
                    "ssid": "Guest-WiFi",
                    "enabled": True,
                    "auth": {"type": "open"},
                    "isolation": True,
                },
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-GUEST")
        assert r is not None
        assert r.status == "pass"

    def test_open_ssid_with_client_isolation_passes(self):
        """An open SSID with client_isolation field should pass."""
        baseline = _snap()
        predicted = _snap(
            wlans={
                "wlan-1": {
                    "ssid": "Guest-WiFi",
                    "enabled": True,
                    "auth": {"type": "open"},
                    "client_isolation": True,
                },
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-GUEST")
        assert r is not None
        assert r.status == "pass"

    def test_psk_wlan_ignored(self):
        """A PSK WLAN should not trigger the open SSID check."""
        baseline = _snap()
        predicted = _snap(
            wlans={
                "wlan-1": {
                    "ssid": "Secure-WiFi",
                    "enabled": True,
                    "auth": {"type": "psk"},
                },
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-GUEST")
        assert r is not None
        assert r.status == "pass"

    def test_missing_auth_type_treated_as_open(self):
        """A WLAN with no auth.type should be treated as open."""
        baseline = _snap()
        predicted = _snap(
            wlans={
                "wlan-1": {
                    "ssid": "NoAuth",
                    "enabled": True,
                    "auth": {},
                },
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-GUEST")
        assert r is not None
        assert r.status == "warning"
        assert "NoAuth" in r.details[0]

    def test_missing_auth_dict_treated_as_open(self):
        """A WLAN with no auth dict at all should be treated as open."""
        baseline = _snap()
        predicted = _snap(
            wlans={
                "wlan-1": {
                    "ssid": "NoAuth",
                    "enabled": True,
                },
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-GUEST")
        assert r is not None
        assert r.status == "warning"

    def test_disabled_wlan_skipped(self):
        """Disabled WLANs should be ignored."""
        baseline = _snap()
        predicted = _snap(
            wlans={
                "wlan-1": {
                    "ssid": "Guest-WiFi",
                    "enabled": False,
                    "auth": {"type": "open"},
                },
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-GUEST")
        assert r is not None
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# TestSecPolicy
# ---------------------------------------------------------------------------


class TestSecPolicy:
    def test_changed_policy_warning(self):
        """Changed security policies should produce a warning."""
        baseline = _snap(
            site_setting={
                "secpolicies": [
                    {"name": "BlockSSH", "action": "deny", "port": 22},
                ],
            }
        )
        predicted = _snap(
            site_setting={
                "secpolicies": [
                    {"name": "BlockSSH", "action": "allow", "port": 22},
                ],
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-POLICY")
        assert r is not None
        assert r.status == "warning"
        assert any("Modified" in d for d in r.details)
        assert any("BlockSSH" in d for d in r.details)

    def test_added_policy_warning(self):
        """Added security policy should produce a warning."""
        baseline = _snap(site_setting={"secpolicies": []})
        predicted = _snap(
            site_setting={
                "secpolicies": [
                    {"name": "NewPolicy", "action": "deny"},
                ],
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-POLICY")
        assert r is not None
        assert r.status == "warning"
        assert any("Added" in d for d in r.details)
        assert any("NewPolicy" in d for d in r.details)

    def test_removed_policy_warning(self):
        """Removed security policy should produce a warning."""
        baseline = _snap(
            site_setting={
                "secpolicies": [
                    {"name": "OldPolicy", "action": "deny"},
                ],
            }
        )
        predicted = _snap(site_setting={"secpolicies": []})
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-POLICY")
        assert r is not None
        assert r.status == "warning"
        assert any("Removed" in d for d in r.details)
        assert any("OldPolicy" in d for d in r.details)

    def test_no_change_passes(self):
        """Identical policies should pass."""
        policies = [{"name": "BlockSSH", "action": "deny", "port": 22}]
        baseline = _snap(site_setting={"secpolicies": policies})
        predicted = _snap(site_setting={"secpolicies": policies})
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-POLICY")
        assert r is not None
        assert r.status == "pass"

    def test_both_empty_passes(self):
        """No policies on either side should pass."""
        baseline = _snap()
        predicted = _snap()
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-POLICY")
        assert r is not None
        assert r.status == "pass"


# ---------------------------------------------------------------------------
# TestSecNac
# ---------------------------------------------------------------------------


class TestSecNac:
    def test_changed_nac_rules_warning(self):
        """Changed NAC rules should produce a warning."""
        baseline = _snap(
            site_setting={
                "nacrules": [
                    {"name": "AllowCorp", "action": "allow"},
                ],
            }
        )
        predicted = _snap(
            site_setting={
                "nacrules": [
                    {"name": "AllowCorp", "action": "allow"},
                    {"name": "BlockGuest", "action": "deny"},
                ],
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-NAC")
        assert r is not None
        assert r.status == "warning"
        assert "1" in r.details[0]  # from 1
        assert "2" in r.details[0]  # to 2

    def test_no_change_passes(self):
        """Identical NAC rules should pass."""
        rules = [{"name": "AllowCorp", "action": "allow"}]
        baseline = _snap(site_setting={"nacrules": rules})
        predicted = _snap(site_setting={"nacrules": rules})
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-NAC")
        assert r is not None
        assert r.status == "pass"

    def test_both_empty_passes(self):
        """No NAC rules on either side should pass."""
        baseline = _snap()
        predicted = _snap()
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-NAC")
        assert r is not None
        assert r.status == "pass"

    def test_rule_content_changed_warning(self):
        """Modified rule content (same count) should produce a warning."""
        baseline = _snap(
            site_setting={
                "nacrules": [
                    {"name": "AllowCorp", "action": "allow"},
                ],
            }
        )
        predicted = _snap(
            site_setting={
                "nacrules": [
                    {"name": "AllowCorp", "action": "deny"},
                ],
            }
        )
        results = check_security(baseline, predicted)
        r = _get_result(results, "SEC-NAC")
        assert r is not None
        assert r.status == "warning"


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestCheckSecurityIntegration:
    def test_returns_three_results(self):
        """check_security always returns exactly 3 CheckResult items."""
        baseline = _snap()
        predicted = _snap()
        results = check_security(baseline, predicted)
        assert len(results) == 3
        ids = {r.check_id for r in results}
        assert ids == {"SEC-GUEST", "SEC-POLICY", "SEC-NAC"}

    def test_all_pass_on_empty_snapshots(self):
        """Empty snapshots should produce all-pass results."""
        baseline = _snap()
        predicted = _snap()
        results = check_security(baseline, predicted)
        for r in results:
            assert r.status == "pass", f"{r.check_id} should pass on empty snapshot but got {r.status}"

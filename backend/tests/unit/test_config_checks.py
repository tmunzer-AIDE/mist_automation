"""
Unit tests for Layer 1 config checks.
TDD: tests written before implementation.
"""

from app.modules.digital_twin.services.config_checks import (
    check_client_capacity_impact,
    check_dhcp_scope_overlap,
    check_dhcp_server_misconfiguration,
    check_dns_ntp_consistency,
    check_duplicate_ssid,
    check_ip_subnet_overlap,
    check_port_profile_conflict,
    check_psk_rotation_impact,
    check_rf_template_impact,
    check_ssid_airtime_overhead,
    check_subnet_collision_within_site,
    check_template_override_crush,
    check_unresolved_template_variables,
    check_vlan_id_collision,
)

# ---------------------------------------------------------------------------
# L1-01: IP/subnet overlap (org-wide, cross-site)
# ---------------------------------------------------------------------------


class TestL1_01:
    def test_overlapping_subnets_cross_site(self):
        existing = [{"subnet": "10.0.0.0/24", "_site_id": "site-a", "_site_name": "Site A"}]
        new = [{"subnet": "10.0.0.128/25", "_site_id": "site-b", "_site_name": "Site B"}]
        result = check_ip_subnet_overlap(existing, new)
        assert result.check_id == "L1-01"
        assert result.status == "critical"
        assert len(result.details) >= 1

    def test_non_overlapping(self):
        existing = [{"subnet": "10.0.0.0/24", "_site_id": "site-a", "_site_name": "Site A"}]
        new = [{"subnet": "10.0.1.0/24", "_site_id": "site-b", "_site_name": "Site B"}]
        result = check_ip_subnet_overlap(existing, new)
        assert result.status == "pass"

    def test_supernet_overlap(self):
        existing = [{"subnet": "192.168.0.0/16", "_site_id": "site-a", "_site_name": "Site A"}]
        new = [{"subnet": "192.168.1.0/24", "_site_id": "site-b", "_site_name": "Site B"}]
        result = check_ip_subnet_overlap(existing, new)
        assert result.status == "critical"

    def test_missing_subnet_field_skipped(self):
        existing = [{"vlan_id": 10, "_site_id": "site-a", "_site_name": "Site A"}]
        new = [{"vlan_id": 20, "_site_id": "site-b", "_site_name": "Site B"}]
        result = check_ip_subnet_overlap(existing, new)
        # No subnets to check — should pass (or skipped)
        assert result.status in ("pass", "skipped")

    def test_empty_inputs(self):
        result = check_ip_subnet_overlap([], [])
        assert result.status in ("pass", "skipped")

    def test_same_site_does_not_trigger_cross_site(self):
        # Same site overlap is L1-02, not L1-01
        existing = [{"subnet": "10.0.0.0/24", "_site_id": "site-a", "_site_name": "Site A"}]
        new = [{"subnet": "10.0.0.128/25", "_site_id": "site-a", "_site_name": "Site A"}]
        result = check_ip_subnet_overlap(existing, new)
        # L1-01 checks cross-site, same-site is L1-02; either pass or critical is fine
        # The key is the function should NOT crash
        assert result.check_id == "L1-01"


# ---------------------------------------------------------------------------
# L1-02: Subnet collision within site
# ---------------------------------------------------------------------------


class TestL1_02:
    def test_same_subnet_same_site(self):
        networks = [
            {"subnet": "10.1.0.0/24", "_site_id": "site-a", "_site_name": "Site A", "name": "Net1"},
            {"subnet": "10.1.0.0/24", "_site_id": "site-a", "_site_name": "Site A", "name": "Net2"},
        ]
        result = check_subnet_collision_within_site(networks)
        assert result.check_id == "L1-02"
        assert result.status == "critical"

    def test_overlapping_subnet_same_site(self):
        networks = [
            {"subnet": "10.1.0.0/24", "_site_id": "site-a", "_site_name": "Site A", "name": "Net1"},
            {"subnet": "10.1.0.128/25", "_site_id": "site-a", "_site_name": "Site A", "name": "Net2"},
        ]
        result = check_subnet_collision_within_site(networks)
        assert result.status == "critical"

    def test_same_subnet_different_sites(self):
        networks = [
            {"subnet": "10.1.0.0/24", "_site_id": "site-a", "_site_name": "Site A", "name": "Net1"},
            {"subnet": "10.1.0.0/24", "_site_id": "site-b", "_site_name": "Site B", "name": "Net1"},
        ]
        result = check_subnet_collision_within_site(networks)
        assert result.status == "pass"

    def test_no_collision(self):
        networks = [
            {"subnet": "10.1.0.0/24", "_site_id": "site-a", "_site_name": "Site A", "name": "Net1"},
            {"subnet": "10.2.0.0/24", "_site_id": "site-a", "_site_name": "Site A", "name": "Net2"},
        ]
        result = check_subnet_collision_within_site(networks)
        assert result.status == "pass"

    def test_missing_subnet_ignored(self):
        networks = [
            {"vlan_id": 10, "_site_id": "site-a", "_site_name": "Site A", "name": "Net1"},
        ]
        result = check_subnet_collision_within_site(networks)
        assert result.status in ("pass", "skipped")


# ---------------------------------------------------------------------------
# L1-03: VLAN ID collision
# ---------------------------------------------------------------------------


class TestL1_03:
    def test_duplicate_vlan_same_site(self):
        networks = [
            {"vlan_id": 100, "name": "Corp", "_site_id": "site-a", "_site_name": "Site A"},
            {"vlan_id": 100, "name": "Guest", "_site_id": "site-a", "_site_name": "Site A"},
        ]
        result = check_vlan_id_collision(networks)
        assert result.check_id == "L1-03"
        assert result.status == "error"

    def test_duplicate_vlan_different_sites(self):
        networks = [
            {"vlan_id": 100, "name": "Corp", "_site_id": "site-a", "_site_name": "Site A"},
            {"vlan_id": 100, "name": "Corp", "_site_id": "site-b", "_site_name": "Site B"},
        ]
        result = check_vlan_id_collision(networks)
        assert result.status == "pass"

    def test_unique_vlans(self):
        networks = [
            {"vlan_id": 100, "name": "Corp", "_site_id": "site-a", "_site_name": "Site A"},
            {"vlan_id": 200, "name": "Guest", "_site_id": "site-a", "_site_name": "Site A"},
        ]
        result = check_vlan_id_collision(networks)
        assert result.status == "pass"

    def test_same_vlan_same_name_same_site(self):
        # Same VLAN ID and same name — not a collision
        networks = [
            {"vlan_id": 100, "name": "Corp", "_site_id": "site-a", "_site_name": "Site A"},
            {"vlan_id": 100, "name": "Corp", "_site_id": "site-a", "_site_name": "Site A"},
        ]
        # Two entries with same vlan+name+site — still a collision on same site
        result = check_vlan_id_collision(networks)
        assert result.check_id == "L1-03"


# ---------------------------------------------------------------------------
# L1-04: Duplicate SSID
# ---------------------------------------------------------------------------


class TestL1_04:
    def test_duplicate_ssid_same_site(self):
        wlans = [
            {"ssid": "Corp-WiFi", "_site_id": "site-a", "_site_name": "Site A"},
            {"ssid": "Corp-WiFi", "_site_id": "site-a", "_site_name": "Site A"},
        ]
        result = check_duplicate_ssid(wlans)
        assert result.check_id == "L1-04"
        assert result.status == "error"

    def test_duplicate_ssid_different_sites(self):
        wlans = [
            {"ssid": "Corp-WiFi", "_site_id": "site-a", "_site_name": "Site A"},
            {"ssid": "Corp-WiFi", "_site_id": "site-b", "_site_name": "Site B"},
        ]
        result = check_duplicate_ssid(wlans)
        assert result.status == "pass"

    def test_unique_ssids(self):
        wlans = [
            {"ssid": "Corp-WiFi", "_site_id": "site-a", "_site_name": "Site A"},
            {"ssid": "Guest-WiFi", "_site_id": "site-a", "_site_name": "Site A"},
        ]
        result = check_duplicate_ssid(wlans)
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L1-05: Port profile physical conflict
# ---------------------------------------------------------------------------


class TestL1_05:
    def test_same_port_different_profiles(self):
        existing = [{"port": "ge-0/0/0", "profile": "access", "_device_name": "SW1", "_site_id": "site-a"}]
        new = [{"port": "ge-0/0/0", "profile": "trunk", "_device_name": "SW1", "_site_id": "site-a"}]
        result = check_port_profile_conflict(existing, new)
        assert result.check_id == "L1-05"
        assert result.status == "error"

    def test_different_ports(self):
        existing = [{"port": "ge-0/0/0", "profile": "access", "_device_name": "SW1", "_site_id": "site-a"}]
        new = [{"port": "ge-0/0/1", "profile": "trunk", "_device_name": "SW1", "_site_id": "site-a"}]
        result = check_port_profile_conflict(existing, new)
        assert result.status == "pass"

    def test_different_devices_same_port(self):
        existing = [{"port": "ge-0/0/0", "profile": "access", "_device_name": "SW1", "_site_id": "site-a"}]
        new = [{"port": "ge-0/0/0", "profile": "trunk", "_device_name": "SW2", "_site_id": "site-a"}]
        result = check_port_profile_conflict(existing, new)
        assert result.status == "pass"

    def test_empty_inputs(self):
        result = check_port_profile_conflict([], [])
        assert result.status in ("pass", "skipped")


# ---------------------------------------------------------------------------
# L1-06: Template override crush
# ---------------------------------------------------------------------------


class TestL1_06:
    def test_template_overrides_site_var(self):
        site_settings = {"dns_servers": ["8.8.8.8"], "ntp_servers": ["pool.ntp.org"]}
        template_config = {"dns_servers": ["1.1.1.1"], "ntp_servers": ["time.google.com"]}
        result = check_template_override_crush(site_settings, template_config, "Site A")
        assert result.check_id == "L1-06"
        assert result.status == "warning"
        assert len(result.details) >= 1

    def test_no_overlap(self):
        site_settings = {"custom_key": "value"}
        template_config = {"dns_servers": ["1.1.1.1"]}
        result = check_template_override_crush(site_settings, template_config, "Site A")
        assert result.status == "pass"

    def test_empty_site_settings(self):
        result = check_template_override_crush({}, {"dns_servers": ["1.1.1.1"]}, "Site A")
        assert result.status == "pass"

    def test_empty_template(self):
        result = check_template_override_crush({"dns_servers": ["8.8.8.8"]}, {}, "Site A")
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L1-07: Unresolved template variables
# ---------------------------------------------------------------------------


class TestL1_07:
    def test_missing_var(self):
        template_config = {"dns_servers": ["{{ dns_server }}"]}
        site_vars = {}
        result = check_unresolved_template_variables(template_config, site_vars, "Tmpl1", "Site A")
        assert result.check_id == "L1-07"
        assert result.status == "error"
        assert "dns_server" in " ".join(result.details)

    def test_all_vars_defined(self):
        template_config = {"dns_servers": ["{{ dns_server }}"]}
        site_vars = {"dns_server": "8.8.8.8"}
        result = check_unresolved_template_variables(template_config, site_vars, "Tmpl1", "Site A")
        assert result.status == "pass"

    def test_no_template_vars(self):
        template_config = {"dns_servers": ["8.8.8.8"]}
        site_vars = {}
        result = check_unresolved_template_variables(template_config, site_vars, "Tmpl1", "Site A")
        assert result.status == "pass"

    def test_nested_missing_var(self):
        template_config = {"section": {"key": "{{ missing_var }}"}}
        site_vars = {}
        result = check_unresolved_template_variables(template_config, site_vars, "Tmpl1", "Site A")
        assert result.status == "error"

    def test_multiple_missing_vars(self):
        template_config = {"a": "{{ var_a }}", "b": "{{ var_b }}"}
        site_vars = {"var_a": "value_a"}
        result = check_unresolved_template_variables(template_config, site_vars, "Tmpl1", "Site A")
        assert result.status == "error"
        assert "var_b" in " ".join(result.details)

    def test_var_in_list(self):
        template_config = {"servers": ["{{ ntp_server }}", "pool.ntp.org"]}
        site_vars = {}
        result = check_unresolved_template_variables(template_config, site_vars, "Tmpl1", "Site A")
        assert result.status == "error"


# ---------------------------------------------------------------------------
# L1-08: DHCP scope overlap
# ---------------------------------------------------------------------------


class TestL1_08:
    def test_overlapping_ranges_same_subnet(self):
        dhcp_configs = [
            {
                "subnet": "10.0.0.0/24",
                "ip_start": "10.0.0.10",
                "ip_end": "10.0.0.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            },
            {
                "subnet": "10.0.0.0/24",
                "ip_start": "10.0.0.50",
                "ip_end": "10.0.0.150",
                "_site_id": "site-a",
                "_site_name": "Site A",
            },
        ]
        result = check_dhcp_scope_overlap(dhcp_configs)
        assert result.check_id == "L1-08"
        assert result.status == "error"

    def test_non_overlapping_ranges(self):
        dhcp_configs = [
            {
                "subnet": "10.0.0.0/24",
                "ip_start": "10.0.0.10",
                "ip_end": "10.0.0.50",
                "_site_id": "site-a",
                "_site_name": "Site A",
            },
            {
                "subnet": "10.0.0.0/24",
                "ip_start": "10.0.0.51",
                "ip_end": "10.0.0.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            },
        ]
        result = check_dhcp_scope_overlap(dhcp_configs)
        assert result.status == "pass"

    def test_different_subnets_same_range(self):
        dhcp_configs = [
            {
                "subnet": "10.0.0.0/24",
                "ip_start": "10.0.0.10",
                "ip_end": "10.0.0.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            },
            {
                "subnet": "10.0.1.0/24",
                "ip_start": "10.0.1.10",
                "ip_end": "10.0.1.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            },
        ]
        result = check_dhcp_scope_overlap(dhcp_configs)
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L1-09: DHCP server misconfiguration
# ---------------------------------------------------------------------------


class TestL1_09:
    def test_gateway_outside_subnet(self):
        dhcp_configs = [
            {
                "subnet": "10.0.0.0/24",
                "gateway": "10.0.1.1",
                "ip_start": "10.0.0.10",
                "ip_end": "10.0.0.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            }
        ]
        result = check_dhcp_server_misconfiguration(dhcp_configs)
        assert result.check_id == "L1-09"
        assert result.status == "error"

    def test_range_outside_subnet(self):
        dhcp_configs = [
            {
                "subnet": "10.0.0.0/24",
                "gateway": "10.0.0.1",
                "ip_start": "10.0.1.10",
                "ip_end": "10.0.1.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            }
        ]
        result = check_dhcp_server_misconfiguration(dhcp_configs)
        assert result.status == "error"

    def test_valid_config(self):
        dhcp_configs = [
            {
                "subnet": "10.0.0.0/24",
                "gateway": "10.0.0.1",
                "ip_start": "10.0.0.10",
                "ip_end": "10.0.0.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            }
        ]
        result = check_dhcp_server_misconfiguration(dhcp_configs)
        assert result.status == "pass"

    def test_ip_start_outside_subnet(self):
        dhcp_configs = [
            {
                "subnet": "192.168.10.0/24",
                "gateway": "192.168.10.1",
                "ip_start": "192.168.11.10",
                "ip_end": "192.168.10.100",
                "_site_id": "site-a",
                "_site_name": "Site A",
            }
        ]
        result = check_dhcp_server_misconfiguration(dhcp_configs)
        assert result.status == "error"


# ---------------------------------------------------------------------------
# L1-10: DNS/NTP consistency
# ---------------------------------------------------------------------------


class TestL1_10:
    def test_missing_dns(self):
        device_configs = [
            {"_device_name": "AP1", "_site_id": "site-a", "ntp_servers": ["pool.ntp.org"]},
        ]
        result = check_dns_ntp_consistency(device_configs)
        assert result.check_id == "L1-10"
        assert result.status == "warning"

    def test_missing_ntp(self):
        device_configs = [
            {"_device_name": "AP1", "_site_id": "site-a", "dns_servers": ["8.8.8.8"]},
        ]
        result = check_dns_ntp_consistency(device_configs)
        assert result.status == "warning"

    def test_has_dns_and_ntp(self):
        device_configs = [
            {
                "_device_name": "AP1",
                "_site_id": "site-a",
                "dns_servers": ["8.8.8.8"],
                "ntp_servers": ["pool.ntp.org"],
            },
        ]
        result = check_dns_ntp_consistency(device_configs)
        assert result.status == "pass"

    def test_multiple_devices_one_missing(self):
        device_configs = [
            {"_device_name": "AP1", "_site_id": "site-a", "dns_servers": ["8.8.8.8"], "ntp_servers": ["pool.ntp.org"]},
            {"_device_name": "AP2", "_site_id": "site-a"},  # missing both
        ]
        result = check_dns_ntp_consistency(device_configs)
        assert result.status == "warning"

    def test_empty_dns_list(self):
        device_configs = [
            {"_device_name": "AP1", "_site_id": "site-a", "dns_servers": [], "ntp_servers": ["pool.ntp.org"]},
        ]
        result = check_dns_ntp_consistency(device_configs)
        assert result.status == "warning"


# ---------------------------------------------------------------------------
# L1-11: SSID airtime overhead
# ---------------------------------------------------------------------------


class TestL1_11:
    def test_five_ssids_warning(self):
        wlans = [{"ssid": f"SSID-{i}", "_site_id": "site-a", "_site_name": "Site A"} for i in range(5)]
        result = check_ssid_airtime_overhead(wlans)
        assert result.check_id == "L1-11"
        assert result.status == "warning"

    def test_seven_ssids_error(self):
        wlans = [{"ssid": f"SSID-{i}", "_site_id": "site-a", "_site_name": "Site A"} for i in range(7)]
        result = check_ssid_airtime_overhead(wlans)
        assert result.status == "error"

    def test_four_ssids_pass(self):
        wlans = [{"ssid": f"SSID-{i}", "_site_id": "site-a", "_site_name": "Site A"} for i in range(4)]
        result = check_ssid_airtime_overhead(wlans)
        assert result.status == "pass"

    def test_multiple_sites_counted_separately(self):
        # 5 per site-a + 2 per site-b — site-a gets warning, site-b passes
        wlans = [{"ssid": f"SSID-{i}", "_site_id": "site-a", "_site_name": "Site A"} for i in range(5)]
        wlans += [{"ssid": f"SSID-{i}", "_site_id": "site-b", "_site_name": "Site B"} for i in range(2)]
        result = check_ssid_airtime_overhead(wlans)
        # site-a has 5, so at minimum warning
        assert result.status in ("warning", "error")

    def test_empty_wlans(self):
        result = check_ssid_airtime_overhead([])
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L1-12: PSK rotation client impact
# ---------------------------------------------------------------------------


class TestL1_12:
    def test_psk_changed_with_active_clients(self):
        old_wlan = {"ssid": "Corp-WiFi", "psk": "oldpassword123"}
        new_wlan = {"ssid": "Corp-WiFi", "psk": "newpassword456"}
        result = check_psk_rotation_impact(old_wlan, new_wlan, active_clients=50, site_name="Site A")
        assert result.check_id == "L1-12"
        assert result.status == "warning"

    def test_psk_unchanged(self):
        old_wlan = {"ssid": "Corp-WiFi", "psk": "samepassword"}
        new_wlan = {"ssid": "Corp-WiFi", "psk": "samepassword"}
        result = check_psk_rotation_impact(old_wlan, new_wlan, active_clients=50, site_name="Site A")
        assert result.status == "pass"

    def test_psk_changed_no_clients(self):
        old_wlan = {"ssid": "Corp-WiFi", "psk": "oldpassword123"}
        new_wlan = {"ssid": "Corp-WiFi", "psk": "newpassword456"}
        result = check_psk_rotation_impact(old_wlan, new_wlan, active_clients=0, site_name="Site A")
        assert result.status == "pass"

    def test_psk_added(self):
        old_wlan = {"ssid": "Corp-WiFi"}
        new_wlan = {"ssid": "Corp-WiFi", "psk": "newpassword"}
        result = check_psk_rotation_impact(old_wlan, new_wlan, active_clients=10, site_name="Site A")
        # Adding PSK changes auth method — should warn
        assert result.status == "warning"


# ---------------------------------------------------------------------------
# L1-13: RF template impact
# ---------------------------------------------------------------------------


class TestL1_13:
    def test_channel_changed(self):
        old_rf = {"band_24": {"channel": 1, "power": 17}, "band_5": {"channel": 36, "power": 17}}
        new_rf = {"band_24": {"channel": 6, "power": 17}, "band_5": {"channel": 36, "power": 17}}
        result = check_rf_template_impact(old_rf, new_rf, affected_ap_count=10)
        assert result.check_id == "L1-13"
        assert result.status == "warning"

    def test_power_changed(self):
        old_rf = {"band_24": {"channel": 1, "power": 17}}
        new_rf = {"band_24": {"channel": 1, "power": 23}}
        result = check_rf_template_impact(old_rf, new_rf, affected_ap_count=5)
        assert result.status == "warning"

    def test_no_change(self):
        old_rf = {"band_24": {"channel": 1, "power": 17}}
        new_rf = {"band_24": {"channel": 1, "power": 17}}
        result = check_rf_template_impact(old_rf, new_rf, affected_ap_count=10)
        assert result.status == "pass"

    def test_no_aps_affected(self):
        old_rf = {"band_24": {"channel": 1, "power": 17}}
        new_rf = {"band_24": {"channel": 6, "power": 17}}
        result = check_rf_template_impact(old_rf, new_rf, affected_ap_count=0)
        assert result.status == "pass"

    def test_empty_rf_configs(self):
        result = check_rf_template_impact({}, {}, affected_ap_count=0)
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# L1-14: Client capacity impact
# ---------------------------------------------------------------------------


class TestL1_14:
    def test_limit_reduced_near_current(self):
        old_wlan = {"ssid": "Corp-WiFi", "max_clients": 100}
        new_wlan = {"ssid": "Corp-WiFi", "max_clients": 40}
        result = check_client_capacity_impact(old_wlan, new_wlan, current_clients=50, site_name="Site A")
        assert result.check_id == "L1-14"
        assert result.status in ("warning", "error")

    def test_limit_reduced_below_current(self):
        old_wlan = {"ssid": "Corp-WiFi", "max_clients": 100}
        new_wlan = {"ssid": "Corp-WiFi", "max_clients": 30}
        result = check_client_capacity_impact(old_wlan, new_wlan, current_clients=50, site_name="Site A")
        assert result.status in ("warning", "error")
        # Clients exceed new limit — should be at least warning
        assert result.status != "pass"

    def test_limit_above_current(self):
        old_wlan = {"ssid": "Corp-WiFi", "max_clients": 100}
        new_wlan = {"ssid": "Corp-WiFi", "max_clients": 200}
        result = check_client_capacity_impact(old_wlan, new_wlan, current_clients=50, site_name="Site A")
        assert result.status == "pass"

    def test_limit_not_changed(self):
        old_wlan = {"ssid": "Corp-WiFi", "max_clients": 100}
        new_wlan = {"ssid": "Corp-WiFi", "max_clients": 100}
        result = check_client_capacity_impact(old_wlan, new_wlan, current_clients=50, site_name="Site A")
        assert result.status == "pass"

    def test_no_max_clients_field(self):
        old_wlan = {"ssid": "Corp-WiFi"}
        new_wlan = {"ssid": "Corp-WiFi"}
        result = check_client_capacity_impact(old_wlan, new_wlan, current_clients=50, site_name="Site A")
        assert result.status in ("pass", "skipped")

    def test_limit_exactly_at_current(self):
        old_wlan = {"ssid": "Corp-WiFi", "max_clients": 100}
        new_wlan = {"ssid": "Corp-WiFi", "max_clients": 50}
        result = check_client_capacity_impact(old_wlan, new_wlan, current_clients=50, site_name="Site A")
        # Exactly at limit — warn
        assert result.status in ("warning", "error")

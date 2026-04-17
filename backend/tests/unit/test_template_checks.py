"""Tests for TMPL-VAR check (template variable resolution)."""

from __future__ import annotations

from app.modules.digital_twin.checks.template_checks import check_template_variables
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


def _make_snapshot(
    site_setting: dict | None = None,
    networks: dict | None = None,
    wlans: dict | None = None,
    devices: dict | None = None,
) -> SiteSnapshot:
    """Build a minimal SiteSnapshot for testing."""
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting=site_setting or {},
        networks=networks or {},
        wlans=wlans or {},
        devices=devices or {},
        port_usages={},
        lldp_neighbors={},
        port_status={},
        ap_clients={},
        port_devices={},
    )


def _make_device(
    device_id: str = "dev-1",
    port_config: dict | None = None,
    ip_config: dict | None = None,
    dhcpd_config: dict | None = None,
    effective_config: dict | None = None,
) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=device_id,
        mac="aabbccddeeff",
        name="switch-1",
        type="switch",
        model="EX4100",
        port_config=port_config or {},
        ip_config=ip_config or {},
        dhcpd_config=dhcpd_config or {},
        effective_config=effective_config,
    )


class TestTmplVar:
    def test_detects_unresolved_variable(self):
        """site_setting has {{ corp_vlan }} but vars only has dns_server."""
        snap = _make_snapshot(
            site_setting={
                "vars": {"dns_server": "8.8.8.8"},
                "networks": {"corp": {"vlan_id": "{{ corp_vlan }}"}},
            },
        )
        results = check_template_variables(snap)
        assert len(results) == 1
        result = results[0]
        assert result.check_id == "TMPL-VAR"
        assert result.status == "error"
        assert any("corp_vlan" in d for d in result.details)

    def test_all_vars_resolved_passes(self):
        """All referenced vars are in site_vars."""
        snap = _make_snapshot(
            site_setting={
                "vars": {"dns_server": "8.8.8.8", "ntp_server": "pool.ntp.org"},
                "dns": ["{{ dns_server }}"],
                "ntp": ["{{ ntp_server }}"],
            },
        )
        results = check_template_variables(snap)
        assert len(results) == 1
        assert results[0].status == "pass"

    def test_handles_null_vars(self):
        """site_setting.vars = None should not crash."""
        snap = _make_snapshot(
            site_setting={
                "vars": None,
                "dns": ["8.8.8.8"],
            },
        )
        results = check_template_variables(snap)
        assert len(results) == 1
        # No template references, so pass
        assert results[0].status == "pass"

    def test_scans_device_configs(self):
        """Variable in device port_config is detected as unresolved."""
        device = _make_device(
            port_config={
                "ge-0/0/0": {"usage": "{{ uplink_profile }}"},
            },
        )
        snap = _make_snapshot(
            site_setting={"vars": {}},
            devices={"dev-1": device},
        )
        results = check_template_variables(snap)
        assert len(results) == 1
        result = results[0]
        assert result.status == "error"
        assert any("uplink_profile" in d for d in result.details)

    def test_device_ip_config_scanned(self):
        """Variable in device ip_config is detected."""
        device = _make_device(
            ip_config={"corp": {"ip": "{{ corp_gw_ip }}", "netmask": "255.255.255.0"}},
        )
        snap = _make_snapshot(
            site_setting={"vars": {"corp_gw_ip": "10.0.0.1"}},
            devices={"dev-1": device},
        )
        results = check_template_variables(snap)
        assert results[0].status == "pass"

    def test_device_dhcpd_config_scanned(self):
        """Variable in device dhcpd_config is detected as unresolved."""
        device = _make_device(
            dhcpd_config={"enabled": True, "servers": ["{{ dhcp_relay }}"]},
        )
        snap = _make_snapshot(
            site_setting={"vars": {}},
            devices={"dev-1": device},
        )
        results = check_template_variables(snap)
        assert results[0].status == "error"
        assert any("dhcp_relay" in d for r in results for d in r.details)

    def test_vars_key_excluded_from_scan(self):
        """Variables defined inside vars dict should not be flagged as references."""
        snap = _make_snapshot(
            site_setting={
                "vars": {"my_var": "{{ some_jinja_looking_default }}"},
            },
        )
        results = check_template_variables(snap)
        # The vars dict itself is excluded from scanning, so no references found
        assert results[0].status == "pass"

    def test_whitespace_control_syntax(self):
        """Jinja2 whitespace control ({{- var }}) is handled."""
        snap = _make_snapshot(
            site_setting={
                "vars": {},
                "gateway": "{{- gw_addr }}",
            },
        )
        results = check_template_variables(snap)
        assert results[0].status == "error"
        assert any("gw_addr" in d for d in results[0].details)

    def test_scans_snapshot_networks(self):
        """Template vars inside snapshot networks are detected."""
        snap = _make_snapshot(
            site_setting={"vars": {}},
            networks={
                "n1": {
                    "name": "Corp",
                    "vlan_id": "{{ corp_vlan }}",
                }
            },
        )
        results = check_template_variables(snap)
        assert results[0].status == "error"
        assert any("corp_vlan" in d for d in results[0].details)

    def test_scans_snapshot_wlans(self):
        """Template vars inside snapshot WLANs are detected."""
        snap = _make_snapshot(
            site_setting={"vars": {}},
            wlans={
                "w1": {
                    "ssid": "guest",
                    "vlan_id": "{{ guest_vlan }}",
                }
            },
        )
        results = check_template_variables(snap)
        assert results[0].status == "error"
        assert any("guest_vlan" in d for d in results[0].details)

    def test_scans_device_effective_config_for_ntp_vars(self):
        """Vars in template-derived switch globals (e.g. ntp_servers) are detected."""
        device = _make_device(
            effective_config={
                "id": "dev-1",
                "type": "switch",
                "ntp_servers": ["{{ site_ntp_server }}"],
            }
        )
        snap = _make_snapshot(site_setting={"vars": {}}, devices={"dev-1": device})

        results = check_template_variables(snap)
        assert results[0].status == "error"
        assert any("site_ntp_server" in d for d in results[0].details)


class TestJinjaLiteralsExcluded:
    """Regression: ``{{ true }}`` / ``{{ false }}`` / ``{{ none }}`` and
    Jinja2 builtins (``range``, ``loop``, …) must NOT be flagged as
    unresolved template variables.
    """

    def test_boolean_literal_not_flagged(self):
        snap = _make_snapshot(
            site_setting={
                "vars": {},
                "enabled": "{{ true }}",
                "disabled": "{{ false }}",
                "nothing": "{{ none }}",
            }
        )
        results = check_template_variables(snap)
        assert len(results) == 1
        assert results[0].status == "pass"

    def test_jinja_builtin_not_flagged(self):
        snap = _make_snapshot(
            site_setting={
                "vars": {},
                # Common Jinja2 builtin callable; previously flagged as unresolved.
                "items": "{{ range(5) }}",
                "loop_ref": "{{ loop.index }}",
            }
        )
        results = check_template_variables(snap)
        assert len(results) == 1
        assert results[0].status == "pass"

    def test_real_undefined_var_still_flagged_alongside_literal(self):
        snap = _make_snapshot(
            site_setting={
                "vars": {},
                "a": "{{ true }}",
                "b": "{{ missing_var }}",
            }
        )
        results = check_template_variables(snap)
        assert len(results) == 1
        assert results[0].status == "error"
        assert any("missing_var" in d for d in results[0].details)
        assert not any("true" in d for d in results[0].details)


class TestCheckDescriptions:
    def test_tmpl_var_description_populated(self):
        """TMPL-VAR populates the description field for both pass and fail outcomes."""
        # fail path
        snap_fail = _make_snapshot(
            site_setting={
                "vars": {},
                "dns": ["{{ undefined_var }}"],
            }
        )
        fail_results = check_template_variables(snap_fail)
        assert fail_results[0].description != ""

        # pass path
        snap_pass = _make_snapshot(site_setting={"vars": {"x": "1"}, "dns": ["{{ x }}"]})
        pass_results = check_template_variables(snap_pass)
        assert pass_results[0].description != ""

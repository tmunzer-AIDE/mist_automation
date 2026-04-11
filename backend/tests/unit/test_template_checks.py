"""Tests for TMPL-VAR check (template variable resolution)."""

from __future__ import annotations

from app.modules.digital_twin.checks.template_checks import check_template_variables
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


def _make_snapshot(
    site_setting: dict | None = None,
    devices: dict | None = None,
) -> SiteSnapshot:
    """Build a minimal SiteSnapshot for testing."""
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting=site_setting or {},
        networks={},
        wlans={},
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

"""
Unit tests for the Digital Twin config compiler.

Tests cover:
- detect_template_changes: identifies org-level template modifications in staged writes
- resolve_vars: recursive {{key}} substitution
- compile_switch_config: switch merge order (derived_setting base + device overrides)
- compile_gateway_config: gw_template → device_profile → device merge with deep port_config
"""

from __future__ import annotations

from typing import Any

from app.modules.digital_twin.models import StagedWrite
from app.modules.digital_twin.services.config_compiler import (
    _deep_merge_port_config,
    compile_gateway_config,
    compile_switch_config,
    detect_template_changes,
    resolve_vars,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sw(sequence: int, method: str, endpoint: str, body: dict | None = None) -> StagedWrite:
    return StagedWrite(sequence=sequence, method=method, endpoint=endpoint, body=body)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# detect_template_changes
# ---------------------------------------------------------------------------


class TestDetectTemplateChanges:
    def test_networktemplate_detected(self) -> None:
        writes = [
            _sw(1, "PUT", "/api/v1/orgs/org1/networktemplates/nt-1", {"name": "new name"}),
        ]
        result = detect_template_changes(writes)
        assert len(result) == 1
        assert result[0]["template_type"] == "networktemplates"
        assert result[0]["template_id"] == "nt-1"
        assert result[0]["assignment_field"] == "networktemplate_id"

    def test_gatewaytemplate_detected(self) -> None:
        writes = [
            _sw(1, "PUT", "/api/v1/orgs/org1/gatewaytemplates/gt-99", {"port_config": {}}),
        ]
        result = detect_template_changes(writes)
        assert len(result) == 1
        assert result[0]["template_type"] == "gatewaytemplates"
        assert result[0]["template_id"] == "gt-99"
        assert result[0]["assignment_field"] == "gatewaytemplate_id"

    def test_sitetemplate_detected(self) -> None:
        writes = [
            _sw(1, "PUT", "/api/v1/orgs/org1/sitetemplates/st-abc", {}),
        ]
        result = detect_template_changes(writes)
        assert len(result) == 1
        assert result[0]["template_type"] == "sitetemplates"
        assert result[0]["assignment_field"] == "sitetemplate_id"

    def test_non_template_endpoint_ignored(self) -> None:
        writes = [
            _sw(1, "PUT", "/api/v1/sites/site1/devices/dev-1", {"name": "switch"}),
            _sw(2, "POST", "/api/v1/orgs/org1/networks", {"vlan_id": 100}),
        ]
        result = detect_template_changes(writes)
        assert result == []

    def test_multiple_templates_detected(self) -> None:
        writes = [
            _sw(1, "PUT", "/api/v1/orgs/org1/networktemplates/nt-1", {}),
            _sw(2, "PUT", "/api/v1/orgs/org1/rftemplates/rf-2", {}),
            _sw(3, "PUT", "/api/v1/sites/site-x/setting", {}),
        ]
        result = detect_template_changes(writes)
        assert len(result) == 2
        types = {r["template_type"] for r in result}
        assert "networktemplates" in types
        assert "rftemplates" in types

    def test_delete_on_template_also_detected(self) -> None:
        writes = [
            _sw(1, "DELETE", "/api/v1/orgs/org1/networktemplates/nt-del"),
        ]
        result = detect_template_changes(writes)
        assert len(result) == 1
        assert result[0]["template_id"] == "nt-del"

    def test_empty_staged_writes(self) -> None:
        assert detect_template_changes([]) == []


# ---------------------------------------------------------------------------
# resolve_vars
# ---------------------------------------------------------------------------


class TestResolveVars:
    def test_string_substitution(self) -> None:
        result = resolve_vars("hello {{name}}", {"name": "world"})
        assert result == "hello world"

    def test_nested_dict(self) -> None:
        data = {"a": {"b": "value is {{x}}"}}
        result = resolve_vars(data, {"x": "42"})
        assert result == {"a": {"b": "value is 42"}}

    def test_list_items(self) -> None:
        data = ["prefix-{{env}}", "plain"]
        result = resolve_vars(data, {"env": "prod"})
        assert result == ["prefix-prod", "plain"]

    def test_undefined_var_left_as_is(self) -> None:
        result = resolve_vars("hello {{missing}}", {"name": "world"})
        assert result == "hello {{missing}}"

    def test_empty_vars_noop(self) -> None:
        data = {"key": "{{val}}"}
        result = resolve_vars(data, {})
        assert result == {"key": "{{val}}"}

    def test_non_string_value_passthrough(self) -> None:
        result = resolve_vars(42, {"x": "y"})
        assert result == 42

    def test_multiple_vars_in_one_string(self) -> None:
        result = resolve_vars("{{a}}-{{b}}", {"a": "foo", "b": "bar"})
        assert result == "foo-bar"


# ---------------------------------------------------------------------------
# compile_switch_config
# ---------------------------------------------------------------------------


class TestCompileSwitchConfig:
    def _make_derived(self, **kwargs: Any) -> dict:
        base = {
            "port_usages": {"default": {"mode": "access"}},
            "networks": {"corp": {"vlan_id": 10}},
            "dhcpd_config": {"enabled": True},
        }
        base.update(kwargs)
        return base

    def _make_device(self, **kwargs: Any) -> dict:
        base: dict = {
            "port_usages": {},
            "networks": {},
            "dhcpd_config": {},
            "port_config": {},
        }
        base.update(kwargs)
        return base

    def test_derived_base_merged_with_empty_device(self) -> None:
        derived = self._make_derived()
        device = self._make_device()
        result = compile_switch_config(derived, device, {})
        assert result["port_usages"] == {"default": {"mode": "access"}}
        assert result["networks"] == {"corp": {"vlan_id": 10}}

    def test_device_overrides_template_port_usage(self) -> None:
        derived = self._make_derived(port_usages={"default": {"mode": "access"}, "voice": {"mode": "trunk"}})
        device = self._make_device(port_usages={"default": {"mode": "trunk", "vlan_id": 99}})
        result = compile_switch_config(derived, device, {})
        # device wins for "default", template-only "voice" is preserved
        assert result["port_usages"]["default"]["mode"] == "trunk"
        assert "voice" in result["port_usages"]

    def test_variable_resolution_in_networks(self) -> None:
        derived = self._make_derived(networks={"corp": {"description": "site {{site_name}}"}})
        device = self._make_device()
        result = compile_switch_config(derived, device, {"site_name": "HQ"})
        assert result["networks"]["corp"]["description"] == "site HQ"

    def test_port_config_deep_merge_preserves_inherited_fields(self) -> None:
        derived = self._make_derived(
            port_config={"ge-0/0/0": {"usage": "trunk", "vlan_id": 100, "poe_disabled": False}}
        )
        device = self._make_device(port_config={"ge-0/0/0": {"poe_disabled": True}})
        result = compile_switch_config(derived, device, {})
        assert result["port_config"]["ge-0/0/0"]["usage"] == "trunk"
        assert result["port_config"]["ge-0/0/0"]["vlan_id"] == 100
        assert result["port_config"]["ge-0/0/0"]["poe_disabled"] is True

    def test_dhcpd_config_merged(self) -> None:
        derived = self._make_derived(dhcpd_config={"enabled": True, "subnet": "10.0.0.0/24"})
        device = self._make_device(dhcpd_config={"subnet": "192.168.1.0/24"})
        result = compile_switch_config(derived, device, {})
        assert result["dhcpd_config"]["enabled"] is True
        assert result["dhcpd_config"]["subnet"] == "192.168.1.0/24"


# ---------------------------------------------------------------------------
# compile_gateway_config
# ---------------------------------------------------------------------------


class TestCompileGatewayConfig:
    def _gw_template(self, **kwargs: Any) -> dict:
        base = {
            "port_usages": {"wan": {"usage": "wan"}},
            "networks": {"corp": {"vlan_id": 10}},
            "dhcpd_config": {"enabled": False},
            "port_config": {"ge-0/0/0": {"usage": "wan", "name": "WAN"}},
            "ip_configs": {"corp": {"ip": "10.0.0.1", "netmask": "/24"}},
        }
        base.update(kwargs)
        return base

    def _device_profile(self, **kwargs: Any) -> dict:
        base: dict = {
            "port_usages": {},
            "networks": {},
            "dhcpd_config": {},
            "port_config": {},
            "ip_configs": {},
        }
        base.update(kwargs)
        return base

    def _device_config(self, **kwargs: Any) -> dict:
        base: dict = {
            "port_usages": {},
            "networks": {},
            "dhcpd_config": {},
            "port_config": {},
            "ip_configs": {},
        }
        base.update(kwargs)
        return base

    def test_template_base_applied(self) -> None:
        result = compile_gateway_config(self._gw_template(), {}, self._device_config(), {})
        assert result["port_usages"]["wan"]["usage"] == "wan"
        assert result["networks"]["corp"]["vlan_id"] == 10

    def test_device_overrides_template(self) -> None:
        gw = self._gw_template(networks={"corp": {"vlan_id": 10}})
        device = self._device_config(networks={"corp": {"vlan_id": 20}})
        result = compile_gateway_config(gw, {}, device, {})
        assert result["networks"]["corp"]["vlan_id"] == 20

    def test_device_profile_in_middle(self) -> None:
        gw = self._gw_template(port_usages={"wan": {"usage": "wan"}})
        profile = self._device_profile(port_usages={"lan": {"usage": "lan"}})
        device = self._device_config(port_usages={"mgmt": {"usage": "mgmt"}})
        result = compile_gateway_config(gw, profile, device, {})
        # All three merged, device wins conflicts
        assert "wan" in result["port_usages"]
        assert "lan" in result["port_usages"]
        assert "mgmt" in result["port_usages"]

    def test_variable_resolution(self) -> None:
        gw = self._gw_template(networks={"corp": {"gateway": "{{gw_ip}}"}})
        result = compile_gateway_config(gw, {}, self._device_config(), {"gw_ip": "10.1.1.1"})
        assert result["networks"]["corp"]["gateway"] == "10.1.1.1"

    def test_deep_merge_port_config(self) -> None:
        gw = self._gw_template(port_config={"ge-0/0/0": {"usage": "wan", "name": "WAN", "wan_type": "broadband"}})
        device = self._device_config(port_config={"ge-0/0/0": {"name": "ISP-Link"}})
        result = compile_gateway_config(gw, {}, device, {})
        # template fields preserved, device name wins
        assert result["port_config"]["ge-0/0/0"]["usage"] == "wan"
        assert result["port_config"]["ge-0/0/0"]["wan_type"] == "broadband"
        assert result["port_config"]["ge-0/0/0"]["name"] == "ISP-Link"

    def test_ip_configs_shallow_merge(self) -> None:
        gw = self._gw_template(ip_configs={"corp": {"ip": "10.0.0.1"}})
        device = self._device_config(ip_configs={"mgmt": {"ip": "192.168.0.1"}})
        result = compile_gateway_config(gw, {}, device, {})
        assert "corp" in result["ip_configs"]
        assert "mgmt" in result["ip_configs"]

    def test_empty_gw_template(self) -> None:
        device = self._device_config(networks={"corp": {"vlan_id": 5}})
        result = compile_gateway_config({}, {}, device, {})
        assert result["networks"]["corp"]["vlan_id"] == 5


# ---------------------------------------------------------------------------
# _deep_merge_port_config (internal helper)
# ---------------------------------------------------------------------------


class TestDeepMergePortConfig:
    def test_non_overlapping_ports(self) -> None:
        a = {"ge-0/0/0": {"usage": "wan"}}
        b = {"ge-0/0/1": {"usage": "lan"}}
        result = _deep_merge_port_config(a, b)
        assert "ge-0/0/0" in result
        assert "ge-0/0/1" in result

    def test_later_wins_on_field_conflict(self) -> None:
        a = {"ge-0/0/0": {"usage": "wan", "name": "old"}}
        b = {"ge-0/0/0": {"name": "new"}}
        result = _deep_merge_port_config(a, b)
        assert result["ge-0/0/0"]["usage"] == "wan"
        assert result["ge-0/0/0"]["name"] == "new"

    def test_none_config_skipped(self) -> None:
        a = {"ge-0/0/0": {"usage": "wan"}}
        result = _deep_merge_port_config(a, None)  # type: ignore[arg-type]
        assert result == {"ge-0/0/0": {"usage": "wan"}}

    def test_empty_configs(self) -> None:
        result = _deep_merge_port_config({}, {})
        assert result == {}

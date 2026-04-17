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
    NETWORK_TEMPLATE_FIELDS,
    _apply_network_template,
    _apply_switch_rules,
    _deep_merge_port_config,
    _match_switch_condition,
    _merge_template_field,
    _process_switch_interface,
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

    def test_deviceprofile_detected(self) -> None:
        writes = [
            _sw(1, "PUT", "/api/v1/orgs/org1/deviceprofiles/dp-sw-standard", {"dns_servers": []}),
        ]
        result = detect_template_changes(writes)
        assert len(result) == 1
        assert result[0]["template_type"] == "deviceprofiles"
        assert result[0]["template_id"] == "dp-sw-standard"
        assert result[0]["assignment_field"] == "deviceprofile_id"


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
    """Tests for compile_switch_config's 5-input chain
    (network_template, site_setting, device_profile, device_config, site_vars).
    """

    def _make_site_setting(self, **kwargs: Any) -> dict:
        base = {
            "port_usages": {"default": {"mode": "access"}},
            "networks": {"corp": {"vlan_id": 10}},
        }
        base.update(kwargs)
        return base

    def _make_device(self, **kwargs: Any) -> dict:
        base: dict = {
            "name": "SW-01",
            "model": "EX4100-48P",
            "role": "access",
        }
        base.update(kwargs)
        return base

    def _compile(
        self,
        *,
        network_template: dict | None = None,
        site_setting: dict | None = None,
        device_profile: dict | None = None,
        device_config: dict | None = None,
        site_vars: dict | None = None,
    ) -> dict[str, Any]:
        return compile_switch_config(
            network_template=network_template,
            site_setting=site_setting or {},
            device_profile=device_profile,
            device_config=device_config or self._make_device(),
            site_vars=site_vars or {},
        )

    def test_site_setting_base_merged_with_empty_device(self) -> None:
        result = self._compile(site_setting=self._make_site_setting())
        assert result["port_usages"] == {"default": {"mode": "access"}}
        assert result["networks"] == {"corp": {"vlan_id": 10}}

    def test_device_overrides_site_setting_port_usage(self) -> None:
        site = self._make_site_setting(port_usages={"default": {"mode": "access"}, "voice": {"mode": "trunk"}})
        device = self._make_device(port_usages={"default": {"mode": "trunk", "vlan_id": 99}})
        result = self._compile(site_setting=site, device_config=device)
        # device wins for "default", template-only "voice" is preserved
        assert result["port_usages"]["default"]["mode"] == "trunk"
        assert "voice" in result["port_usages"]

    def test_variable_resolution_in_networks(self) -> None:
        site = self._make_site_setting(networks={"corp": {"description": "site {{site_name}}"}})
        result = self._compile(site_setting=site, site_vars={"site_name": "HQ"})
        assert result["networks"]["corp"]["description"] == "site HQ"

    def test_rule_port_config_applies_to_matching_switch(self) -> None:
        # Template-level port_config is filtered out, but rule-level
        # port_config flows through when the rule matches.
        template = {
            "switch_matching": {
                "enable": True,
                "rules": [
                    {
                        "name": "access",
                        "match_role": "access",
                        "port_config": {"ge-0/0/0": {"usage": "trunk", "vlan_id": 100, "poe_disabled": False}},
                    }
                ],
            }
        }
        device = self._make_device(port_config={"ge-0/0/0": {"poe_disabled": True}})
        result = self._compile(network_template=template, device_config=device)
        assert result["port_config"]["ge-0/0/0"]["usage"] == "trunk"
        assert result["port_config"]["ge-0/0/0"]["vlan_id"] == 100
        assert result["port_config"]["ge-0/0/0"]["poe_disabled"] is True

    def test_dhcpd_config_dropped_from_site_setting(self) -> None:
        # In Mist, dhcpd_config is NOT in NETWORK_TEMPLATE_FIELDS — it's a
        # gateway concept. Switches do not inherit dhcpd_config from the
        # site setting; only device-level dhcpd_config flows through.
        site = self._make_site_setting(dhcpd_config={"enabled": True, "subnet": "10.0.0.0/24"})
        device = self._make_device(dhcpd_config={"subnet": "192.168.1.0/24"})
        result = self._compile(site_setting=site, device_config=device)
        assert result.get("dhcpd_config") == {"subnet": "192.168.1.0/24"}
        assert "enabled" not in result["dhcpd_config"]

    def test_rule_matches_by_name_prefix(self) -> None:
        # match_name[0:2] checks "SW" prefix — the switch named "SW-CORE-01"
        # matches and gets the rule's dns_servers. A different switch does not.
        template = {
            "switch_matching": {
                "enable": True,
                "rules": [
                    {
                        "name": "sw-prefix",
                        "match_name[0:2]": "SW",
                        "dns_servers": ["8.8.8.8"],
                    }
                ],
            }
        }
        matching = self._make_device(name="SW-CORE-01")
        non_matching = self._make_device(name="AP-LOBBY")

        result_match = self._compile(network_template=template, device_config=matching)
        result_miss = self._compile(network_template=template, device_config=non_matching)

        assert result_match.get("dns_servers") == ["8.8.8.8"]
        assert "dns_servers" not in result_miss

    def test_device_profile_overlays_template(self) -> None:
        template = {
            "dns_servers": ["1.1.1.1"],
            "networks": {"corp": {"vlan_id": 10}},
        }
        profile = {
            "dns_servers": ["9.9.9.9"],
            "networks": {"guest": {"vlan_id": 20}},
        }
        result = self._compile(network_template=template, device_profile=profile)
        # Lists concatenate (matches mistmcp merge semantics)
        assert result["dns_servers"] == ["1.1.1.1", "9.9.9.9"]
        # Dicts shallow-merge
        assert result["networks"] == {"corp": {"vlan_id": 10}, "guest": {"vlan_id": 20}}

    def test_range_notation_in_rule_collides_with_device_port(self) -> None:
        # Template rule has port_config with a range key. After expansion,
        # the device override for a single port in the range merges
        # deeply (usage inherited, poe_disabled overridden on just one port).
        template = {
            "switch_matching": {
                "enable": True,
                "rules": [
                    {
                        "name": "access",
                        "match_role": "access",
                        "port_config": {
                            "ge-0/0/1-3": {"usage": "trunk", "vlan_id": 100},
                        },
                    }
                ],
            }
        }
        device = self._make_device(role="access", port_config={"ge-0/0/2": {"poe_disabled": True}})
        result = self._compile(network_template=template, device_config=device)

        # Every expanded port carries template usage + vlan_id
        for port in ("ge-0/0/1", "ge-0/0/2", "ge-0/0/3"):
            assert result["port_config"][port]["usage"] == "trunk"
            assert result["port_config"][port]["vlan_id"] == 100
        # Device override only affects ge-0/0/2
        assert result["port_config"]["ge-0/0/2"]["poe_disabled"] is True
        assert "poe_disabled" not in result["port_config"]["ge-0/0/1"]


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


# ---------------------------------------------------------------------------
# compile_base_state
# ---------------------------------------------------------------------------


class TestCompileBaseState:
    """compile_base_state must emit template-merged per-device configs for
    the baseline, so the Twin's baseline snapshot is symmetric with the
    compiled predicted state. Without this, PORT-DISC and CONN-VLAN-PATH
    compare raw-backup baseline data against compiled predicted data and
    miss port profile changes entirely.
    """

    async def test_returns_empty_for_no_sites(self, monkeypatch) -> None:
        from app.modules.digital_twin.services import config_compiler

        calls: list[str] = []

        async def fake_compile_site_devices(state, site_id, org_id, template_changes, cache=None):
            calls.append(site_id)

        async def fake_preload_cache(affected_sites, org_id):
            return {}

        monkeypatch.setattr(config_compiler, "_compile_site_devices", fake_compile_site_devices)
        monkeypatch.setattr(config_compiler, "_preload_compile_cache", fake_preload_cache)

        state = await config_compiler.compile_base_state([], "org-1")
        assert state == {}
        assert calls == []

    async def test_calls_compile_site_devices_per_site(self, monkeypatch) -> None:
        from app.modules.digital_twin.services import config_compiler

        observed_args: list[tuple] = []

        async def fake_compile_site_devices(state, site_id, org_id, template_changes, cache=None):
            observed_args.append((dict(state), site_id, org_id, list(template_changes)))
            # Simulate compile writing one device entry
            state[("devices", site_id, f"dev-{site_id}")] = {
                "id": f"dev-{site_id}",
                "type": "switch",
                "port_config": {"ge-0/0/0": {"usage": "trunk"}},
            }

        async def fake_preload_cache(affected_sites, org_id):
            return {}

        monkeypatch.setattr(config_compiler, "_compile_site_devices", fake_compile_site_devices)
        monkeypatch.setattr(config_compiler, "_preload_compile_cache", fake_preload_cache)

        state = await config_compiler.compile_base_state(["site-a", "site-b"], "org-1")

        # Each site gets compiled with empty template_changes (no staged writes)
        assert [c[1] for c in observed_args] == ["site-a", "site-b"]
        assert all(c[2] == "org-1" for c in observed_args)
        assert all(c[3] == [] for c in observed_args)

        # Resulting state contains compiled device entries keyed by (devices, site, id)
        assert ("devices", "site-a", "dev-site-a") in state
        assert ("devices", "site-b", "dev-site-b") in state
        assert state[("devices", "site-a", "dev-site-a")]["port_config"]["ge-0/0/0"]["usage"] == "trunk"


# ---------------------------------------------------------------------------
# _process_switch_interface (port_config comma/range expansion)
# ---------------------------------------------------------------------------


class TestProcessSwitchInterface:
    """Mistmcp reference: _process_switch_interface, lines 1278-1310."""

    def test_expands_port_range(self) -> None:
        result = _process_switch_interface({"ge-0/0/1-10": {"usage": "trunk"}})
        assert set(result.keys()) == {f"ge-0/0/{i}" for i in range(1, 11)}
        assert all(v == {"usage": "trunk"} for v in result.values())

    def test_expands_comma_list(self) -> None:
        result = _process_switch_interface({"ge-0/0/1,ge-0/0/2": {"usage": "ap"}})
        assert set(result.keys()) == {"ge-0/0/1", "ge-0/0/2"}
        assert all(v == {"usage": "ap"} for v in result.values())

    def test_passes_through_single_port(self) -> None:
        result = _process_switch_interface({"ge-0/0/1": {"usage": "access"}})
        assert result == {"ge-0/0/1": {"usage": "access"}}

    def test_range_on_fpc(self) -> None:
        result = _process_switch_interface({"ge-0-1/0/0": {"usage": "uplink"}})
        assert set(result.keys()) == {"ge-0/0/0", "ge-1/0/0"}

    def test_range_on_pic(self) -> None:
        result = _process_switch_interface({"ge-0/0-1/0": {"usage": "uplink"}})
        assert set(result.keys()) == {"ge-0/0/0", "ge-0/1/0"}

    def test_malformed_key_passes_through(self) -> None:
        # Keys with fewer than two dashes fall through unchanged
        result = _process_switch_interface({"ge-notvalid": {"usage": "x"}})
        assert result == {"ge-notvalid": {"usage": "x"}}

    def test_reversed_range_passes_key_through_rather_than_emitting_empty(self) -> None:
        """Reversed ranges (start > end) previously produced an empty Python
        ``range`` and silently dropped the key, leaving port_config with gaps.
        The fix preserves the original key so the misconfiguration remains
        visible to checks/preflight.
        """
        for key in ("ge-9-0/0/0", "ge-0/9-0/0", "ge-0/0/9-0"):
            result = _process_switch_interface({key: {"usage": "trunk"}})
            assert key in result
            assert result[key] == {"usage": "trunk"}


# ---------------------------------------------------------------------------
# _match_switch_condition
# ---------------------------------------------------------------------------


class TestMatchSwitchCondition:
    """Mistmcp reference: _process_switch_rule_match, lines 1259-1275."""

    def test_exact_case_insensitive_match(self) -> None:
        assert _match_switch_condition("EX4100-48P", "match_model", "ex4100-48p") is True
        assert _match_switch_condition("ex4100-48p", "match_model", "EX4100-48P") is True

    def test_exact_mismatch(self) -> None:
        assert _match_switch_condition("EX4100-48P", "match_model", "QFX5120") is False

    def test_substring_bracket_match(self) -> None:
        # match_name[0:2] checks chars [0:2] == "SW"
        assert _match_switch_condition("SW-CORE-01", "match_name[0:2]", "SW") is True

    def test_substring_bracket_mismatch(self) -> None:
        assert _match_switch_condition("AP-CORE-01", "match_name[0:2]", "SW") is False

    def test_substring_bracket_out_of_range_returns_false(self) -> None:
        assert _match_switch_condition("SW", "match_name[0:10]", "SW") is False

    def test_substring_bracket_malformed_returns_false(self) -> None:
        assert _match_switch_condition("SW-01", "match_name[broken]", "SW") is False


# ---------------------------------------------------------------------------
# _apply_switch_rules (first-match-wins)
# ---------------------------------------------------------------------------


class TestApplySwitchRules:
    """Mistmcp reference: _process_switch_rule, lines 1211-1256."""

    def test_first_match_wins_second_rule_ignored(self) -> None:
        rules = [
            {"name": "first", "match_name[0:2]": "SW", "dns_servers": ["1.1.1.1"]},
            {"name": "second", "match_name[0:2]": "SW", "dns_servers": ["2.2.2.2"]},
        ]
        data: dict[str, Any] = {}
        _apply_switch_rules(rules, "SW-01", "EX4100-48P", "access", data)
        assert data == {"dns_servers": ["1.1.1.1"]}

    def test_all_enabled_conditions_must_pass(self) -> None:
        # Rule requires BOTH match_name AND match_model. Only match_name passes.
        rules = [
            {
                "name": "strict",
                "match_name[0:2]": "SW",
                "match_model": "QFX5120",
                "dns_servers": ["10.0.0.1"],
            }
        ]
        data: dict[str, Any] = {}
        _apply_switch_rules(rules, "SW-01", "EX4100-48P", "access", data)
        assert data == {}  # rule skipped because match_model failed

    def test_rule_with_no_conditions_matches_unconditionally(self) -> None:
        rules = [{"name": "catchall", "dns_servers": ["9.9.9.9"]}]
        data: dict[str, Any] = {}
        _apply_switch_rules(rules, "SW-01", "EX4100-48P", "access", data)
        assert data == {"dns_servers": ["9.9.9.9"]}

    def test_port_config_in_rule_is_expanded(self) -> None:
        rules = [
            {
                "name": "core",
                "match_role": "core",
                "port_config": {"ge-0/0/1-3": {"usage": "uplink"}},
            }
        ]
        data: dict[str, Any] = {}
        _apply_switch_rules(rules, "SW-01", "EX4100", "core", data)
        assert set(data["port_config"].keys()) == {"ge-0/0/1", "ge-0/0/2", "ge-0/0/3"}


# ---------------------------------------------------------------------------
# _apply_network_template (top-level template processor)
# ---------------------------------------------------------------------------


class TestApplyNetworkTemplate:
    """Mistmcp reference: _process_switch_template, lines 1182-1208."""

    def test_filters_non_allowlist_fields(self) -> None:
        template = {
            "networks": {"corp": {"vlan_id": 10}},  # in allowlist
            "created_time": 1234567890,  # NOT in allowlist
            "name": "My Template",  # explicitly skipped
        }
        data: dict[str, Any] = {}
        _apply_network_template(template, "SW-01", "EX4100", "access", data)
        assert "networks" in data
        assert "created_time" not in data
        assert "name" not in data

    def test_switch_matching_disabled_ignores_rules(self) -> None:
        template = {
            "switch_matching": {
                "enable": False,
                "rules": [{"name": "x", "dns_servers": ["1.1.1.1"]}],
            }
        }
        data: dict[str, Any] = {}
        _apply_network_template(template, "SW-01", "EX4100", "access", data)
        assert "dns_servers" not in data  # rules not evaluated because enable=False

    def test_switch_matching_enabled_applies_rules(self) -> None:
        template = {
            "switch_matching": {
                "enable": True,
                "rules": [{"name": "x", "match_role": "access", "dns_servers": ["8.8.8.8"]}],
            }
        }
        data: dict[str, Any] = {}
        _apply_network_template(template, "SW-01", "EX4100", "access", data)
        assert data["dns_servers"] == ["8.8.8.8"]


# ---------------------------------------------------------------------------
# _merge_template_field (single-field merge helper)
# ---------------------------------------------------------------------------


class TestMergeTemplateField:
    def test_port_config_expanded_and_merged(self) -> None:
        data: dict[str, Any] = {"port_config": {"ge-0/0/0": {"usage": "mgmt"}}}
        _merge_template_field(data, "port_config", {"ge-0/0/1-2": {"usage": "access"}})
        assert data["port_config"] == {
            "ge-0/0/0": {"usage": "mgmt"},
            "ge-0/0/1": {"usage": "access"},
            "ge-0/0/2": {"usage": "access"},
        }

    def test_dict_shallow_merge(self) -> None:
        data: dict[str, Any] = {"networks": {"a": 1}}
        _merge_template_field(data, "networks", {"b": 2})
        assert data["networks"] == {"a": 1, "b": 2}

    def test_list_concatenates(self) -> None:
        data: dict[str, Any] = {"dns_servers": ["1.1.1.1"]}
        _merge_template_field(data, "dns_servers", ["8.8.8.8"])
        assert data["dns_servers"] == ["1.1.1.1", "8.8.8.8"]

    def test_scalar_overwrites(self) -> None:
        data: dict[str, Any] = {"fips_enabled": False}
        _merge_template_field(data, "fips_enabled", True)
        assert data["fips_enabled"] is True

    def test_network_template_fields_pinned(self) -> None:
        # Defensive check: if the constant drifts, downstream tests would
        # silently start failing in surprising ways. Keep these pinned.
        # Note: port_config is DELIBERATELY not in the allowlist — in Mist,
        # top-level template port_config is dropped; port_config only flows
        # through switch_matching.rules[matched] and device-level config.
        # This matches the mistmcp reference implementation.
        for key in ("networks", "port_usages", "switch_matching", "dhcp_snooping", "dns_servers"):
            assert key in NETWORK_TEMPLATE_FIELDS
        assert "port_config" not in NETWORK_TEMPLATE_FIELDS  # by design


# ---------------------------------------------------------------------------
# _compile_site_devices orchestration (Phase D)
# ---------------------------------------------------------------------------


class TestCompileSiteDevicesOrchestration:
    """End-to-end _compile_site_devices tests that exercise the real compile
    functions by mocking the I/O boundaries (_get_site_info,
    _get_site_setting, _load_template, _load_device_profile,
    load_all_objects_of_type).
    """

    async def _run_compile(
        self,
        monkeypatch,
        *,
        site_info: dict,
        site_setting: dict | None = None,
        network_template: dict | None = None,
        gateway_template: dict | None = None,
        device_profile: dict | None = None,
        devices: list[dict],
        staged_state: dict | None = None,
    ) -> dict[tuple, dict[str, Any]]:
        from app.modules.digital_twin.services import config_compiler

        async def fake_get_site_info(site_id, org_id, state):
            return dict(site_info)

        async def fake_get_site_setting(site_id, org_id):
            return dict(site_setting or {})

        async def fake_load_template(state, object_type, template_id, org_id, cache=None):
            if not template_id:
                return {}
            if object_type == "networktemplates":
                return dict(network_template or {})
            if object_type == "gatewaytemplates":
                return dict(gateway_template or {})
            return {}

        async def fake_load_device_profile(device_config, org_id, state, cache=None):
            if device_config.get("deviceprofile_id") and device_profile is not None:
                return dict(device_profile)
            return None

        async def fake_load_all_objects(org_id, object_type, site_id=None, org_level_only=False):
            return list(devices)

        monkeypatch.setattr(config_compiler, "_get_site_info", fake_get_site_info)
        monkeypatch.setattr(config_compiler, "_get_site_setting", fake_get_site_setting)
        monkeypatch.setattr(config_compiler, "_load_template", fake_load_template)
        monkeypatch.setattr(config_compiler, "_load_device_profile", fake_load_device_profile)
        from app.modules.digital_twin.services import state_resolver

        monkeypatch.setattr(state_resolver, "load_all_objects_of_type", fake_load_all_objects)

        state = dict(staged_state or {})
        await config_compiler._compile_site_devices(state, "site-1", "org-1", [])
        return state

    async def test_loads_network_template_for_switch(self, monkeypatch) -> None:
        # Template defines port_usages + networks + rule-level port_config.
        template = {
            "port_usages": {"ap": {"mode": "trunk"}},
            "networks": {"corp": {"vlan_id": 10}},
            "switch_matching": {
                "enable": True,
                "rules": [
                    {
                        "name": "access",
                        "match_role": "access",
                        "port_config": {"ge-0/0/9": {"usage": "ap"}},
                    }
                ],
            },
        }
        switch = {
            "id": "sw-1",
            "type": "switch",
            "name": "SW-01",
            "model": "EX4100-48P",
            "role": "access",
        }
        state = await self._run_compile(
            monkeypatch,
            site_info={"networktemplate_id": "nt-1"},
            network_template=template,
            devices=[switch],
        )
        compiled = state[("devices", "site-1", "sw-1")]
        assert compiled["port_usages"]["ap"]["mode"] == "trunk"
        assert compiled["networks"]["corp"]["vlan_id"] == 10
        assert compiled["port_config"]["ge-0/0/9"]["usage"] == "ap"

    async def test_applies_device_profile_to_switch(self, monkeypatch) -> None:
        switch = {
            "id": "sw-1",
            "type": "switch",
            "name": "SW-01",
            "model": "EX4100-48P",
            "role": "access",
            "deviceprofile_id": "dp-1",
        }
        state = await self._run_compile(
            monkeypatch,
            # site_info must carry networktemplate_id so _load_template
            # actually returns the test network_template
            site_info={"networktemplate_id": "nt-1"},
            network_template={"networks": {"corp": {"vlan_id": 10}}},
            device_profile={"dns_servers": ["8.8.8.8"]},
            devices=[switch],
        )
        compiled = state[("devices", "site-1", "sw-1")]
        assert compiled["dns_servers"] == ["8.8.8.8"]
        assert compiled["networks"]["corp"]["vlan_id"] == 10

    async def test_staged_site_setting_overlays_template(self, monkeypatch) -> None:
        # Template says networks={corp: vlan_id=10}; site_setting overrides
        # the same network with vlan_id=20. Site_setting should win because
        # it's applied *after* the template in the compile chain.
        state = await self._run_compile(
            monkeypatch,
            site_info={"networktemplate_id": "nt-1"},
            network_template={"networks": {"corp": {"vlan_id": 10}}},
            site_setting={"networks": {"corp": {"vlan_id": 20}}},
            devices=[
                {
                    "id": "sw-1",
                    "type": "switch",
                    "name": "SW-01",
                    "model": "EX4100-48P",
                    "role": "access",
                }
            ],
        )
        compiled = state[("devices", "site-1", "sw-1")]
        assert compiled["networks"]["corp"]["vlan_id"] == 20

    async def test_device_port_config_flows_through(self, monkeypatch) -> None:
        # The canonical ge-0/0/9 scenario: template rule sets usage=ap, a
        # staged write changes it to iot. Baseline has ap, predicted has iot.
        template = {
            "switch_matching": {
                "enable": True,
                "rules": [
                    {
                        "name": "access",
                        "match_role": "access",
                        "port_config": {"ge-0/0/9": {"usage": "ap"}},
                    }
                ],
            }
        }
        switch = {
            "id": "sw-1",
            "type": "switch",
            "name": "SW-01",
            "model": "EX4100-48P",
            "role": "access",
            "port_config": {"ge-0/0/9": {"usage": "iot"}},  # device override
        }
        state = await self._run_compile(
            monkeypatch,
            site_info={"networktemplate_id": "nt-1"},
            network_template=template,
            devices=[switch],
        )
        compiled = state[("devices", "site-1", "sw-1")]
        # Device override wins: iot replaces ap via deep per-port merge
        assert compiled["port_config"]["ge-0/0/9"]["usage"] == "iot"


# ---------------------------------------------------------------------------
# _preload_compile_cache (Phase D.bis)
# ---------------------------------------------------------------------------


class TestPreloadCompileCache:
    """Verify _preload_compile_cache loads each shared template/profile
    exactly once and negatively caches missing entries.
    """

    async def test_deduplicates_shared_template(self, monkeypatch) -> None:
        from app.modules.digital_twin.services import config_compiler, state_resolver

        # Both sites share the same network_template_id "nt-shared"
        site_infos = {
            "site-a": {"networktemplate_id": "nt-shared"},
            "site-b": {"networktemplate_id": "nt-shared"},
        }

        async def fake_get_site_info(site_id, org_id, state):
            return site_infos.get(site_id, {})

        async def fake_load_all_objects(org_id, object_type, site_id=None, org_level_only=False):
            return []

        monkeypatch.setattr(config_compiler, "_get_site_info", fake_get_site_info)
        monkeypatch.setattr(state_resolver, "load_all_objects_of_type", fake_load_all_objects)

        # Count backup queries by wrapping BackupObject.find
        query_count = {"n": 0}

        class _FakeFind:
            def __init__(self, query):
                query_count["n"] += 1

            def sort(self, *_args, **_kwargs):
                return self

            async def first_or_none(self):
                return None

        from app.modules.backup import models as backup_models

        monkeypatch.setattr(backup_models.BackupObject, "find", classmethod(lambda cls, q: _FakeFind(q)))

        cache = await config_compiler._preload_compile_cache(["site-a", "site-b"], "org-1")

        # Exactly one query for the shared template despite two sites
        assert query_count["n"] == 1
        # Cache stores a negative entry for the missing template
        assert ("networktemplates", "nt-shared") in cache
        assert cache[("networktemplates", "nt-shared")] is None

    async def test_negative_cache_prevents_reload_via_load_template(self, monkeypatch) -> None:
        from app.modules.digital_twin.services import config_compiler

        cache: config_compiler.CompileCache = {("networktemplates", "nt-missing"): None}

        # This should NOT call BackupObject.find because the cache already
        # has a (negative) entry for this key.
        call_count = {"n": 0}

        class _ShouldNotBeCalled:
            def __init__(self, query):
                call_count["n"] += 1

            def sort(self, *_args, **_kwargs):
                return self

            async def first_or_none(self):
                return None

        from app.modules.backup import models as backup_models

        monkeypatch.setattr(
            backup_models.BackupObject,
            "find",
            classmethod(lambda cls, q: _ShouldNotBeCalled(q)),
        )

        result = await config_compiler._load_template({}, "networktemplates", "nt-missing", "org-1", cache=cache)

        assert result == {}
        assert call_count["n"] == 0  # cache hit, no backup query

    async def test_cache_returns_deep_copy(self, monkeypatch) -> None:
        """Regression: the template cache must return a deep copy so callers
        that mutate nested dicts (port_config, networks) don't poison the
        shared cache entry for subsequent sites.
        """
        from app.modules.digital_twin.services import config_compiler

        shared_cached = {
            "port_config": {"ge-0/0/0": {"usage": "trunk"}},
            "networks": ["a", "b"],
        }
        cache: config_compiler.CompileCache = {("networktemplates", "nt-shared"): shared_cached}

        first = await config_compiler._load_template({}, "networktemplates", "nt-shared", "org-1", cache=cache)
        # Mutate a nested dict in the caller's copy.
        first["port_config"]["ge-0/0/0"]["usage"] = "mutated"

        second = await config_compiler._load_template({}, "networktemplates", "nt-shared", "org-1", cache=cache)
        # The second load must see the original value, not the mutation.
        assert second["port_config"]["ge-0/0/0"]["usage"] == "trunk"
        # And the underlying cache entry must also be pristine.
        assert shared_cached["port_config"]["ge-0/0/0"]["usage"] == "trunk"


# ---------------------------------------------------------------------------
# find_impacted_sites (Phase E — device profile scan branch)
# ---------------------------------------------------------------------------


class TestFindImpactedSites:
    """Verify find_impacted_sites branches correctly for device profiles."""

    async def test_deviceprofile_scans_devices_and_returns_sites(self, monkeypatch) -> None:
        from app.modules.backup import models as backup_models
        from app.modules.digital_twin.services import config_compiler

        observed_pipelines: list[list[dict]] = []

        class _FakeAggregate:
            def __init__(self, pipeline):
                observed_pipelines.append(pipeline)

            def __aiter__(self):
                async def _gen():
                    for sid in ("site-a", "site-b"):
                        yield {"_id": sid}

                return _gen()

        monkeypatch.setattr(
            backup_models.BackupObject,
            "aggregate",
            classmethod(lambda cls, pipeline: _FakeAggregate(pipeline)),
        )

        result = await config_compiler.find_impacted_sites("deviceprofiles", "dp-1", "org-1")

        assert sorted(result) == ["site-a", "site-b"]
        assert len(observed_pipelines) == 1
        match_stage = observed_pipelines[0][0]["$match"]
        # Confirms the device-scan path: querying devices, not info
        assert match_stage["object_type"] == "devices"
        assert match_stage["configuration.deviceprofile_id"] == "dp-1"


# ---------------------------------------------------------------------------
# _get_site_info fallback compatibility
# ---------------------------------------------------------------------------


class TestGetSiteInfoFallback:
    class _FakeCursor:
        def __init__(self, docs, query):
            self.docs = docs
            self.query = query

        def sort(self, *_args, **_kwargs):
            return self

        async def first_or_none(self):
            for doc in self.docs:
                if all(doc.get(k) == v for k, v in self.query.items()):
                    return doc
            return None

    class _FakeBackupObject:
        docs: list[dict[str, Any]] = []

        @classmethod
        def find(cls, query):
            return TestGetSiteInfoFallback._FakeCursor(cls.docs, query)

    async def test_prefers_info_shape(self, monkeypatch) -> None:
        from app.modules.backup import models as backup_models
        from app.modules.digital_twin.services import config_compiler

        self._FakeBackupObject.docs = [
            {
                "object_type": "info",
                "site_id": "site-1",
                "org_id": "org-1",
                "is_deleted": False,
                "configuration": {"networktemplate_id": "nt-1"},
            }
        ]
        monkeypatch.setattr(backup_models, "BackupObject", self._FakeBackupObject)

        result = await config_compiler._get_site_info("site-1", "org-1", state={})
        assert result.get("networktemplate_id") == "nt-1"

    async def test_falls_back_to_legacy_site_shape(self, monkeypatch) -> None:
        from app.modules.backup import models as backup_models
        from app.modules.digital_twin.services import config_compiler

        self._FakeBackupObject.docs = [
            {
                "object_type": "site",
                "object_id": "site-1",
                "org_id": "org-1",
                "is_deleted": False,
                "configuration": {"networktemplate_id": "nt-legacy"},
            }
        ]
        monkeypatch.setattr(backup_models, "BackupObject", self._FakeBackupObject)

        result = await config_compiler._get_site_info("site-1", "org-1", state={})
        assert result.get("networktemplate_id") == "nt-legacy"

    async def test_falls_back_to_org_sites_shape(self, monkeypatch) -> None:
        from app.modules.backup import models as backup_models
        from app.modules.digital_twin.services import config_compiler

        self._FakeBackupObject.docs = [
            {
                "object_type": "sites",
                "object_id": "site-1",
                "org_id": "org-1",
                "is_deleted": False,
                "configuration": {"networktemplate_id": "nt-org-sites"},
            }
        ]
        monkeypatch.setattr(backup_models, "BackupObject", self._FakeBackupObject)

        result = await config_compiler._get_site_info("site-1", "org-1", state={})
        assert result.get("networktemplate_id") == "nt-org-sites"

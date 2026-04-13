"""Unit tests for digital twin topology materialization helpers."""

from __future__ import annotations

from app.modules.digital_twin.services.topology_utils import (
    build_network_name_to_vlan,
    materialize_device_port_config,
    materialize_port_config_entry,
)


def test_materialize_port_config_flattens_profile_attrs_on_interface() -> None:
    net_map = {"mgmt": 10, "voice": 20, "data": 30}
    port_usages = {
        "uplink": {
            "mode": "trunk",
            "all_networks": False,
            "networks": ["mgmt", "voice"],
            "stp_edge": False,
        }
    }

    materialized = materialize_port_config_entry(
        {"usage": "uplink", "stp_edge": True},
        port_usages,
        net_map,
    )

    # Profile attributes are copied onto the interface, but interface-local
    # keys still win when both exist.
    assert materialized["mode"] == "trunk"
    assert materialized["all_networks"] is False
    assert materialized["stp_edge"] is True
    assert materialized["resolved_mode"] == "trunk"
    assert materialized["resolved_vlan_ids"] == [10, 20]


def test_materialize_port_config_resolves_all_networks_var_and_expands_vlans() -> None:
    site_vars = {"uplink_all": False}
    networks = {
        "n1": {"name": "corp", "vlan_id": "{{ corp_vlan }}"},
        "n2": {"name": "guest", "vlan_id": 200},
        "n3": {"name": "voice", "vlan_id": 300},
    }
    site_vars["corp_vlan"] = 100
    net_map = build_network_name_to_vlan(networks, site_vars)

    materialized = materialize_port_config_entry(
        {"usage": "uplink"},
        {
            "uplink": {
                "mode": "trunk",
                "all_networks": "{{ uplink_all }}",
                "networks": ["guest", "voice"],
            }
        },
        net_map,
        site_vars,
    )

    assert materialized["resolved_vlan_ids"] == [200, 300]


def test_materialize_device_port_config_handles_direct_trunk_and_disabled() -> None:
    net_map = {"corp": 100, "guest": 200}

    materialized = materialize_device_port_config(
        {
            "ge-0/0/1": {"usage": "trunk"},
            "ge-0/0/2": {"usage": "disabled"},
        },
        site_port_usages={},
        device_port_usages=None,
        network_name_to_vlan=net_map,
    )

    assert materialized["ge-0/0/1"]["resolved_vlan_ids"] == [100, 200]
    assert materialized["ge-0/0/2"]["resolved_vlan_ids"] == []

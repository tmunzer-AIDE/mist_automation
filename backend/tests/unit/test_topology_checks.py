"""
Unit tests for Layer 2 topology checks.
TDD: tests written before implementation.
"""

import pytest

from app.modules.digital_twin.services.topology_checks import (
    check_connectivity_loss,
    check_lacp_misconfiguration,
    check_lag_mclag_integrity,
    check_mtu_mismatch,
    check_poe_budget_overrun,
    check_poe_disable_on_active,
    check_port_capacity_saturation,
    check_vc_integrity,
    check_vlan_black_hole,
)

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _dev(dev_id: str, device_type: str = "switch", **kwargs) -> dict:
    """Create a minimal device dict."""
    d = {
        "id": dev_id,
        "name": kwargs.get("name", dev_id.upper()),
        "mac": kwargs.get("mac", f"aa:bb:cc:00:00:{dev_id[-2:]}"),
        "model": kwargs.get("model", "EX4100-48P"),
        "device_type": device_type,
        "status": kwargs.get("status", "connected"),
        "ip": kwargs.get("ip", "10.0.0.1"),
        "is_virtual_chassis": kwargs.get("is_virtual_chassis", False),
        "vc_mac": kwargs.get("vc_mac", ""),
        "mclag_domain_id": kwargs.get("mclag_domain_id", ""),
        "dhcpd_config": kwargs.get("dhcpd_config", {}),
        "alarm_count": kwargs.get("alarm_count", 0),
    }
    # Allow extra keys (mtu, poe_disabled_ports, etc.)
    for k, v in kwargs.items():
        if k not in d:
            d[k] = v
    return d


def _conn(
    local: str,
    remote: str,
    link_type: str = "STANDALONE",
    status: str = "UP",
    vlan_summary: str = "",
    physical_links_count: int = 1,
    local_ae: str | None = None,
    remote_ae: str | None = None,
) -> dict:
    """Create a minimal connection dict."""
    return {
        "local_device_id": local,
        "remote_device_id": remote,
        "link_type": link_type,
        "status": status,
        "local_ae": local_ae,
        "remote_ae": remote_ae,
        "vlan_summary": vlan_summary,
        "physical_links_count": physical_links_count,
    }


def _make_snapshot(
    devices: dict | None = None,
    connections: list | None = None,
    logical_groups: list | None = None,
    vlan_map: dict | None = None,
    site_id: str = "s1",
    site_name: str = "Branch-1",
) -> dict:
    """Create a minimal topology snapshot dict."""
    devs = devices or {}
    conns = connections or []
    return {
        "site_id": site_id,
        "site_name": site_name,
        "device_count": len(devs),
        "connection_count": len(conns),
        "devices": devs,
        "connections": conns,
        "logical_groups": logical_groups or [],
        "vlan_map": vlan_map or {},
    }


# ---------------------------------------------------------------------------
# L2-01: Connectivity loss
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_01_ConnectivityLoss:
    def test_detects_lost_gateway_path(self):
        baseline = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch"), "gw1": _dev("gw1", "gateway")},
            connections=[_conn("sw1", "gw1")],
        )
        predicted = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch"), "gw1": _dev("gw1", "gateway")},
            connections=[],
        )
        result = check_connectivity_loss(baseline, predicted)
        assert result.check_id == "L2-01"
        assert result.status == "critical"
        assert "sw1" in result.affected_objects or "SW1" in str(result.details)

    def test_passes_when_path_maintained(self):
        baseline = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch"), "gw1": _dev("gw1", "gateway")},
            connections=[_conn("sw1", "gw1")],
        )
        result = check_connectivity_loss(baseline, baseline)
        assert result.status == "pass"

    def test_multi_hop_path_preserved(self):
        devices = {
            "sw1": _dev("sw1", "switch"),
            "sw2": _dev("sw2", "switch"),
            "gw1": _dev("gw1", "gateway"),
        }
        baseline = _make_snapshot(
            devices=devices,
            connections=[_conn("sw1", "sw2"), _conn("sw2", "gw1")],
        )
        result = check_connectivity_loss(baseline, baseline)
        assert result.status == "pass"

    def test_no_gateways_skipped(self):
        baseline = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch")},
            connections=[],
        )
        result = check_connectivity_loss(baseline, baseline)
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-02: VLAN black hole
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_02_VlanBlackHole:
    def test_detects_vlan_unreachable_to_gateway(self):
        """VLAN 100 on sw1 but the connection to gw1 only carries VLAN 200."""
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch"), "gw1": _dev("gw1", "gateway")},
            connections=[_conn("sw1", "gw1", vlan_summary="trunk:200")],
            vlan_map={"Staff": "100", "Guest": "200"},
        )
        result = check_vlan_black_hole(snap)
        assert result.check_id == "L2-02"
        assert result.status == "error"
        assert "100" in str(result.details) or "Staff" in str(result.details)

    def test_passes_when_vlans_reach_gateway(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch"), "gw1": _dev("gw1", "gateway")},
            connections=[_conn("sw1", "gw1", vlan_summary="trunk:100,200")],
            vlan_map={"Staff": "100", "Guest": "200"},
        )
        result = check_vlan_black_hole(snap)
        assert result.status == "pass"

    def test_empty_vlan_map_skipped(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch"), "gw1": _dev("gw1", "gateway")},
            connections=[_conn("sw1", "gw1")],
            vlan_map={},
        )
        result = check_vlan_black_hole(snap)
        assert result.status == "skipped"

    def test_no_gateways_skipped(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1", "switch")},
            connections=[],
            vlan_map={"Staff": "100"},
        )
        result = check_vlan_black_hole(snap)
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-03: LAG/MCLAG integrity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_03_LagMclagIntegrity:
    def test_detects_degraded_lag(self):
        baseline = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2", link_type="LAG", physical_links_count=4, local_ae="ae0")],
        )
        predicted = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2", link_type="LAG", physical_links_count=2, local_ae="ae0")],
        )
        result = check_lag_mclag_integrity(baseline, predicted)
        assert result.check_id == "L2-03"
        assert result.status == "error"

    def test_passes_when_lag_unchanged(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2", link_type="LAG", physical_links_count=4, local_ae="ae0")],
        )
        result = check_lag_mclag_integrity(snap, snap)
        assert result.status == "pass"

    def test_skipped_no_lags(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2")],
        )
        result = check_lag_mclag_integrity(snap, snap)
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-04: VC integrity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_04_VcIntegrity:
    def test_detects_member_removal(self):
        baseline = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2"), "sw3": _dev("sw3")},
            logical_groups=[{"group_type": "VC", "group_id": "vc-1", "member_ids": ["sw1", "sw2", "sw3"]}],
        )
        predicted = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            logical_groups=[{"group_type": "VC", "group_id": "vc-1", "member_ids": ["sw1", "sw2"]}],
        )
        result = check_vc_integrity(baseline, predicted)
        assert result.check_id == "L2-04"
        assert result.status == "critical"
        assert "sw3" in str(result.details) or "SW3" in str(result.details)

    def test_passes_when_vc_unchanged(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            logical_groups=[{"group_type": "VC", "group_id": "vc-1", "member_ids": ["sw1", "sw2"]}],
        )
        result = check_vc_integrity(snap, snap)
        assert result.status == "pass"

    def test_skipped_no_vcs(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1")},
            logical_groups=[],
        )
        result = check_vc_integrity(snap, snap)
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-05: PoE budget overrun
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_05_PoeBudgetOverrun:
    def test_detects_overrun(self):
        snap = _make_snapshot(
            devices={
                "sw1": _dev("sw1"),
                "ap1": _dev("ap1", "ap"),
                "ap2": _dev("ap2", "ap"),
            },
            connections=[
                _conn("sw1", "ap1"),
                _conn("sw1", "ap2"),
            ],
        )
        # sw1 has 30W budget but 2 APs drawing power — we pass per-device budget
        poe_budgets = {"sw1": 30.0}
        result = check_poe_budget_overrun(snap, poe_budgets)
        assert result.check_id == "L2-05"
        # With default 15.4W per AP, 2 APs = 30.8W > 30W
        assert result.status == "error"

    def test_passes_within_budget(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "ap1": _dev("ap1", "ap")},
            connections=[_conn("sw1", "ap1")],
        )
        poe_budgets = {"sw1": 100.0}
        result = check_poe_budget_overrun(snap, poe_budgets)
        assert result.status == "pass"

    def test_skipped_empty_budgets(self):
        snap = _make_snapshot(devices={"sw1": _dev("sw1")})
        result = check_poe_budget_overrun(snap, {})
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-06: PoE disable on active port
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_06_PoeDisableOnActive:
    def test_detects_poe_disabled_on_active(self):
        baseline = _make_snapshot(
            devices={"sw1": _dev("sw1", poe_disabled_ports=[])},
        )
        predicted = _make_snapshot(
            devices={"sw1": _dev("sw1", poe_disabled_ports=["ge-0/0/1", "ge-0/0/2"])},
        )
        active_poe_ports = {"sw1": ["ge-0/0/1"]}
        result = check_poe_disable_on_active(baseline, predicted, active_poe_ports)
        assert result.check_id == "L2-06"
        assert result.status == "critical"
        assert "ge-0/0/1" in str(result.details)

    def test_passes_no_conflict(self):
        baseline = _make_snapshot(
            devices={"sw1": _dev("sw1", poe_disabled_ports=[])},
        )
        predicted = _make_snapshot(
            devices={"sw1": _dev("sw1", poe_disabled_ports=["ge-0/0/5"])},
        )
        active_poe_ports = {"sw1": ["ge-0/0/1"]}
        result = check_poe_disable_on_active(baseline, predicted, active_poe_ports)
        assert result.status == "pass"

    def test_skipped_empty_active(self):
        snap = _make_snapshot(devices={"sw1": _dev("sw1")})
        result = check_poe_disable_on_active(snap, snap, {})
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-07: Port capacity saturation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_07_PortCapacitySaturation:
    def test_detects_oversubscription(self):
        snap = _make_snapshot(devices={"sw1": _dev("sw1")})
        port_counts = {"sw1": (50, 48)}  # 50 used of 48 total
        result = check_port_capacity_saturation(snap, port_counts)
        assert result.check_id == "L2-07"
        assert result.status == "error"

    def test_passes_within_capacity(self):
        snap = _make_snapshot(devices={"sw1": _dev("sw1")})
        port_counts = {"sw1": (24, 48)}
        result = check_port_capacity_saturation(snap, port_counts)
        assert result.status == "pass"

    def test_warns_high_utilization(self):
        snap = _make_snapshot(devices={"sw1": _dev("sw1")})
        port_counts = {"sw1": (44, 48)}  # ~92% used
        result = check_port_capacity_saturation(snap, port_counts)
        assert result.status == "warning"

    def test_skipped_empty(self):
        snap = _make_snapshot(devices={"sw1": _dev("sw1")})
        result = check_port_capacity_saturation(snap, {})
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-08: LACP misconfiguration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_08_LacpMisconfiguration:
    def test_detects_single_link_lag(self):
        """A LAG with only 1 physical link is suspicious."""
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2", link_type="LAG", physical_links_count=1, local_ae="ae0")],
        )
        result = check_lacp_misconfiguration(snap)
        assert result.check_id == "L2-08"
        assert result.status == "warning"

    def test_passes_healthy_lag(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2", link_type="LAG", physical_links_count=2, local_ae="ae0")],
        )
        result = check_lacp_misconfiguration(snap)
        assert result.status == "pass"

    def test_skipped_no_lag(self):
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2")],
        )
        result = check_lacp_misconfiguration(snap)
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# L2-09: MTU mismatch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestL2_09_MtuMismatch:
    def test_detects_mismatch(self):
        snap = _make_snapshot(
            devices={
                "sw1": _dev("sw1", mtu=9000),
                "sw2": _dev("sw2", mtu=1500),
            },
            connections=[_conn("sw1", "sw2")],
        )
        result = check_mtu_mismatch(snap)
        assert result.check_id == "L2-09"
        assert result.status == "warning"

    def test_passes_matching_mtu(self):
        snap = _make_snapshot(
            devices={
                "sw1": _dev("sw1", mtu=9000),
                "sw2": _dev("sw2", mtu=9000),
            },
            connections=[_conn("sw1", "sw2")],
        )
        result = check_mtu_mismatch(snap)
        assert result.status == "pass"

    def test_passes_no_mtu_set(self):
        """When neither device has MTU set, no mismatch."""
        snap = _make_snapshot(
            devices={"sw1": _dev("sw1"), "sw2": _dev("sw2")},
            connections=[_conn("sw1", "sw2")],
        )
        result = check_mtu_mismatch(snap)
        assert result.status == "pass"

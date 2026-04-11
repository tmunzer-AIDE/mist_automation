"""
Unit tests for snapshot-based connectivity checks (CONN-PHYS, CONN-VLAN).
"""

from __future__ import annotations

from app.modules.digital_twin.checks.connectivity import check_connectivity
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dev(
    device_id: str,
    mac: str,
    name: str,
    dtype: str = "switch",
    port_config: dict | None = None,
    ip_config: dict | None = None,
) -> DeviceSnapshot:
    """Build a minimal DeviceSnapshot."""
    return DeviceSnapshot(
        device_id=device_id,
        mac=mac,
        name=name,
        type=dtype,
        model="test-model",
        port_config=port_config or {},
        ip_config=ip_config or {},
        dhcpd_config={},
    )


def _snap(
    devices: dict[str, DeviceSnapshot] | None = None,
    networks: dict[str, dict] | None = None,
    port_usages: dict[str, dict] | None = None,
    lldp_neighbors: dict[str, dict[str, str]] | None = None,
    ap_clients: dict[str, int] | None = None,
) -> SiteSnapshot:
    """Build a minimal SiteSnapshot with sensible defaults."""
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting={},
        networks=networks or {},
        wlans={},
        devices=devices or {},
        port_usages=port_usages or {},
        lldp_neighbors=lldp_neighbors or {},
        port_status={},
        ap_clients=ap_clients or {},
        port_devices={},
    )


# ---------------------------------------------------------------------------
# CONN-PHYS: Physical Connectivity Loss
# ---------------------------------------------------------------------------


class TestConnPhys:
    """Tests for the CONN-PHYS check (physical connectivity loss)."""

    def test_detects_disconnected_device(self):
        """Removing an LLDP link isolates a switch from the gateway."""
        gw = _dev("gw1", "aa:00:00:00:00:01", "gateway-1", "gateway")
        sw1 = _dev("sw1", "aa:00:00:00:00:02", "switch-1", "switch")
        sw2 = _dev("sw2", "aa:00:00:00:00:03", "switch-2", "switch")

        devices = {"gw1": gw, "sw1": sw1, "sw2": sw2}

        # Baseline: gw -- sw1 -- sw2 (all connected)
        baseline = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
                "aa:00:00:00:00:02": {"ge-0/0/1": "aa:00:00:00:00:03"},
            },
        )

        # Predicted: gw -- sw1, sw2 isolated (link sw1-sw2 removed)
        predicted = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            },
        )

        results = check_connectivity(baseline, predicted)
        phys = next(r for r in results if r.check_id == "CONN-PHYS")

        assert phys.status == "critical"  # switch isolation is critical
        assert phys.layer == 2
        assert len(phys.details) == 1
        assert "switch-2" in phys.details[0]
        assert "sw2" in phys.affected_objects

    def test_no_change_passes(self):
        """Identical baseline and predicted -> pass."""
        gw = _dev("gw1", "aa:00:00:00:00:01", "gateway-1", "gateway")
        sw1 = _dev("sw1", "aa:00:00:00:00:02", "switch-1", "switch")

        devices = {"gw1": gw, "sw1": sw1}
        lldp = {"aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"}}

        baseline = _snap(devices=devices, lldp_neighbors=lldp)
        predicted = _snap(devices=devices, lldp_neighbors=lldp)

        results = check_connectivity(baseline, predicted)
        phys = next(r for r in results if r.check_id == "CONN-PHYS")

        assert phys.status == "pass"

    def test_ap_with_clients_is_critical(self):
        """Isolating an AP that has clients is critical."""
        gw = _dev("gw1", "aa:00:00:00:00:01", "gateway-1", "gateway")
        sw1 = _dev("sw1", "aa:00:00:00:00:02", "switch-1", "switch")
        ap1 = _dev("ap1", "aa:00:00:00:00:03", "ap-1", "ap")

        devices = {"gw1": gw, "sw1": sw1, "ap1": ap1}

        baseline = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
                "aa:00:00:00:00:02": {"ge-0/0/1": "aa:00:00:00:00:03"},
            },
            ap_clients={"ap1": 15},
        )

        # Remove link to AP
        predicted = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            },
            ap_clients={"ap1": 15},
        )

        results = check_connectivity(baseline, predicted)
        phys = next(r for r in results if r.check_id == "CONN-PHYS")

        assert phys.status == "critical"
        assert "15 clients" in phys.details[0]

    def test_ap_without_clients_is_error(self):
        """Isolating an AP with zero clients is error, not critical."""
        gw = _dev("gw1", "aa:00:00:00:00:01", "gateway-1", "gateway")
        ap1 = _dev("ap1", "aa:00:00:00:00:02", "ap-idle", "ap")

        devices = {"gw1": gw, "ap1": ap1}

        baseline = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            },
        )
        predicted = _snap(
            devices=devices,
            lldp_neighbors={},
        )

        results = check_connectivity(baseline, predicted)
        phys = next(r for r in results if r.check_id == "CONN-PHYS")

        assert phys.status == "error"

    def test_no_gateways_skipped(self):
        """When there are no gateways, the check is skipped."""
        sw1 = _dev("sw1", "aa:00:00:00:00:01", "switch-1", "switch")

        baseline = _snap(devices={"sw1": sw1})
        predicted = _snap(devices={"sw1": sw1})

        results = check_connectivity(baseline, predicted)
        phys = next(r for r in results if r.check_id == "CONN-PHYS")

        assert phys.status == "skipped"


# ---------------------------------------------------------------------------
# CONN-VLAN: VLAN Gateway Reachability
# ---------------------------------------------------------------------------


class TestConnVlan:
    """Tests for the CONN-VLAN check (VLAN gateway reachability)."""

    def test_detects_vlan_losing_gateway(self):
        """Removing a gateway ip_config entry causes VLAN to lose L3."""
        networks = {
            "net-1": {"name": "data", "vlan_id": 100},
            "net-2": {"name": "mgmt", "vlan_id": 200},
        }

        # Baseline: gateway has L3 on both VLANs
        gw_baseline = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={
                "data": {"ip": "10.0.0.1", "netmask": "255.255.255.0"},
                "mgmt": {"ip": "10.0.1.1", "netmask": "255.255.255.0"},
            },
        )
        sw1 = _dev("sw1", "aa:00:00:00:00:02", "switch-1", "switch")
        lldp = {"aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"}}

        baseline = _snap(
            devices={"gw1": gw_baseline, "sw1": sw1},
            networks=networks,
            lldp_neighbors=lldp,
        )

        # Predicted: gateway loses L3 on data VLAN
        gw_predicted = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={
                "mgmt": {"ip": "10.0.1.1", "netmask": "255.255.255.0"},
            },
        )

        predicted = _snap(
            devices={"gw1": gw_predicted, "sw1": sw1},
            networks=networks,
            lldp_neighbors=lldp,
        )

        results = check_connectivity(baseline, predicted)
        vlan_check = next(r for r in results if r.check_id == "CONN-VLAN")

        assert vlan_check.status == "critical"
        assert vlan_check.layer == 2
        assert len(vlan_check.details) == 1
        assert "VLAN 100" in vlan_check.details[0]
        assert "data" in vlan_check.details[0]
        assert "vlan-100" in vlan_check.affected_objects

    def test_no_change_passes(self):
        """Identical gateway ip_config -> pass."""
        networks = {
            "net-1": {"name": "data", "vlan_id": 100},
        }
        gw = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={"data": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
        )

        snap = _snap(devices={"gw1": gw}, networks=networks)

        results = check_connectivity(snap, snap)
        vlan_check = next(r for r in results if r.check_id == "CONN-VLAN")

        assert vlan_check.status == "pass"

    def test_multiple_vlans_lost(self):
        """Removing all ip_config entries loses multiple VLANs."""
        networks = {
            "net-1": {"name": "data", "vlan_id": 100},
            "net-2": {"name": "voice", "vlan_id": 200},
        }
        gw_baseline = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={
                "data": {"ip": "10.0.0.1", "netmask": "255.255.255.0"},
                "voice": {"ip": "10.0.1.1", "netmask": "255.255.255.0"},
            },
        )
        gw_predicted = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={},
        )

        baseline = _snap(devices={"gw1": gw_baseline}, networks=networks)
        predicted = _snap(devices={"gw1": gw_predicted}, networks=networks)

        results = check_connectivity(baseline, predicted)
        vlan_check = next(r for r in results if r.check_id == "CONN-VLAN")

        assert vlan_check.status == "critical"
        assert len(vlan_check.details) == 2
        assert "vlan-100" in vlan_check.affected_objects
        assert "vlan-200" in vlan_check.affected_objects

    def test_no_networks_passes(self):
        """No networks defined -> no VLANs to lose -> pass."""
        gw = _dev("gw1", "aa:00:00:00:00:01", "gateway-1", "gateway")
        snap = _snap(devices={"gw1": gw})

        results = check_connectivity(snap, snap)
        vlan_check = next(r for r in results if r.check_id == "CONN-VLAN")

        assert vlan_check.status == "pass"

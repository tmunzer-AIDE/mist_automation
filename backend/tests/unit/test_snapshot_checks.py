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
    wlans: dict[str, dict] | None = None,
    port_devices: dict[str, dict[str, str]] | None = None,
) -> SiteSnapshot:
    """Build a minimal SiteSnapshot with sensible defaults."""
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting={},
        networks=networks or {},
        wlans=wlans or {},
        devices=devices or {},
        port_usages=port_usages or {},
        lldp_neighbors=lldp_neighbors or {},
        port_status={},
        ap_clients=ap_clients or {},
        port_devices=port_devices or {},
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


# ---------------------------------------------------------------------------
# CONN-VLAN-PATH: Per-VLAN gateway path reachability
# ---------------------------------------------------------------------------


class TestConnVlanPath:
    """Tests for CONN-VLAN-PATH — detects AP/switch blackholes caused by
    upstream port profile changes that drop a VLAN from a trunk, even when
    the physical LLDP link stays up.
    """

    def _trunk_profile(self) -> dict[str, dict]:
        return {
            "ap": {"mode": "trunk"},  # allows every VLAN
            "iot": {"mode": "access", "port_network": "iot-net", "vlan_id": 20},
        }

    def _wlan_site_snapshot(
        self,
        switch_port_usage: str,
    ) -> SiteSnapshot:
        """Build a (gw -- switch -- ap) site where the AP serves a WLAN on
        VLAN 10 and the switch port to the AP uses the given profile."""
        networks = {
            "net-data": {"name": "corp-data", "vlan_id": 10},
            "net-iot": {"name": "iot-net", "vlan_id": 20},
        }
        port_usages = self._trunk_profile()
        wlans = {"wlan-1": {"id": "wlan-1", "ssid": "Corp", "vlan_id": 10}}

        gw = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={
                "corp-data": {"ip": "10.0.10.1", "netmask": "255.255.255.0"},
                "iot-net": {"ip": "10.0.20.1", "netmask": "255.255.255.0"},
            },
        )
        sw1 = _dev(
            "sw1",
            "aa:00:00:00:00:02",
            "US-NY-SWA-01",
            "switch",
            port_config={
                "ge-0/0/0": {"usage": "ap"},  # uplink to gateway (full trunk)
                "ge-0/0/9": {"usage": switch_port_usage},
            },
        )
        ap1 = _dev("ap1", "aa:00:00:00:00:03", "AP-LOBBY", "ap")

        return _snap(
            devices={"gw1": gw, "sw1": sw1, "ap1": ap1},
            networks=networks,
            port_usages=port_usages,
            wlans=wlans,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
                "aa:00:00:00:00:02": {
                    "ge-0/0/0": "aa:00:00:00:00:01",
                    "ge-0/0/9": "aa:00:00:00:00:03",
                },
            },
        )

    def test_detects_ap_blackhole_on_profile_change(self):
        """Changing the AP uplink port from full-trunk 'ap' to 'iot' drops
        VLAN 10 — the AP loses gateway reachability in the VLAN 10 subgraph
        even though the physical LLDP link is intact."""
        baseline = self._wlan_site_snapshot(switch_port_usage="ap")
        predicted = self._wlan_site_snapshot(switch_port_usage="iot")

        results = check_connectivity(baseline, predicted)
        path = next(r for r in results if r.check_id == "CONN-VLAN-PATH")

        assert path.status == "critical"
        assert path.layer == 2
        assert any("AP-LOBBY" in d and "VLAN 10" in d for d in path.details)
        assert any("Corp" in d for d in path.details)
        assert "ap1" in path.affected_objects

    def test_detects_ap_blackhole_from_port_devices_with_logical_port_id(self):
        """AP edge should still be modelled when LLDP misses it but port_devices
        reports it as ge-0/0/9.0.
        """
        networks = {
            "net-data": {"name": "corp-data", "vlan_id": 10},
            "net-iot": {"name": "iot-net", "vlan_id": 20},
        }
        port_usages = {
            "ap": {"mode": "trunk"},
            "iot": {"mode": "access", "port_network": "iot-net", "vlan_id": 20},
        }
        wlans = {"wlan-1": {"id": "wlan-1", "ssid": "Corp", "vlan_id": 10}}

        gw = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gateway-1",
            "gateway",
            ip_config={
                "corp-data": {"ip": "10.0.10.1", "netmask": "255.255.255.0"},
                "iot-net": {"ip": "10.0.20.1", "netmask": "255.255.255.0"},
            },
        )
        sw_base = _dev(
            "sw1",
            "aa:00:00:00:00:02",
            "US-NY-SWA-01",
            "switch",
            port_config={
                "ge-0/0/0": {"usage": "ap"},
                "ge-0/0/9": {"usage": "ap"},
            },
        )
        sw_pred = _dev(
            "sw1",
            "aa:00:00:00:00:02",
            "US-NY-SWA-01",
            "switch",
            port_config={
                "ge-0/0/0": {"usage": "ap"},
                "ge-0/0/9": {"usage": "iot"},
            },
        )
        ap = _dev("ap1", "aa:00:00:00:00:03", "AP-LOBBY", "ap")

        # LLDP reports only gw<->switch. AP edge comes from port_devices using
        # a logical-unit key (ge-0/0/9.0) that must map to ge-0/0/9.
        lldp = {
            "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01"},
        }
        port_devices = {
            "aa:00:00:00:00:02": {"ge-0/0/9.0": "aa:00:00:00:00:03"},
        }

        baseline = _snap(
            devices={"gw1": gw, "sw1": sw_base, "ap1": ap},
            networks=networks,
            port_usages=port_usages,
            wlans=wlans,
            lldp_neighbors=lldp,
            port_devices=port_devices,
        )
        predicted = _snap(
            devices={"gw1": gw, "sw1": sw_pred, "ap1": ap},
            networks=networks,
            port_usages=port_usages,
            wlans=wlans,
            lldp_neighbors=lldp,
            port_devices=port_devices,
        )

        results = check_connectivity(baseline, predicted)
        path = next(r for r in results if r.check_id == "CONN-VLAN-PATH")

        assert path.status == "critical"
        assert any("AP-LOBBY" in d and "VLAN 10" in d for d in path.details)
        assert "ap1" in path.affected_objects

    def test_pass_when_baseline_equals_predicted(self):
        """No change -> no reachability loss."""
        snap = self._wlan_site_snapshot(switch_port_usage="ap")

        results = check_connectivity(snap, snap)
        path = next(r for r in results if r.check_id == "CONN-VLAN-PATH")

        assert path.status == "pass"

    def test_pass_when_wlan_vlan_is_unresolved_jinja(self):
        """WLAN with a Jinja-templated vlan_id is not added to any subgraph,
        so there is nothing to blackhole."""
        base = self._wlan_site_snapshot(switch_port_usage="ap")
        pred = self._wlan_site_snapshot(switch_port_usage="iot")
        base.wlans["wlan-1"]["vlan_id"] = "{{wlan_vlan}}"
        pred.wlans["wlan-1"]["vlan_id"] = "{{wlan_vlan}}"

        results = check_connectivity(base, pred)
        path = next(r for r in results if r.check_id == "CONN-VLAN-PATH")

        # AP still drops from VLAN 10 subgraph for the switch's port change,
        # but the AP is no longer modelled in VLAN 10, so only the switch
        # would be flagged if at all. With a full-trunk uplink in baseline
        # the switch still reaches the gateway on VLAN 20, so no loss.
        assert path.status in ("pass", "error")
        assert not any("AP-LOBBY" in d for d in path.details)

    def test_switch_loses_vlan_path_is_error(self):
        """Switch (not AP) losing a VLAN path is an error, not critical."""
        # Baseline: switch has a trunk to AP-less downstream; predicted drops
        # the VLAN via a port profile that only carries VLAN 20.
        networks = {"net-data": {"name": "data", "vlan_id": 10}}
        port_usages = {
            "trunk": {"mode": "trunk"},
            "iot": {"mode": "access", "port_network": "iot", "vlan_id": 20},
        }
        gw = _dev(
            "gw1",
            "aa:00:00:00:00:01",
            "gw-1",
            "gateway",
            ip_config={"data": {"ip": "10.0.10.1", "netmask": "255.255.255.0"}},
        )
        sw_up = _dev(
            "sw1",
            "aa:00:00:00:00:02",
            "sw-up",
            "switch",
            port_config={
                "ge-0/0/0": {"usage": "trunk"},
                "ge-0/0/1": {"usage": "trunk"},
            },
        )
        # In baseline, sw-down has VLAN 10 via trunk; in predicted it uses iot
        sw_down_base = _dev(
            "sw2",
            "aa:00:00:00:00:03",
            "sw-down",
            "switch",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
        )
        sw_down_pred = _dev(
            "sw2",
            "aa:00:00:00:00:03",
            "sw-down",
            "switch",
            port_config={"ge-0/0/0": {"usage": "iot"}},
        )
        lldp = {
            "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            "aa:00:00:00:00:02": {
                "ge-0/0/0": "aa:00:00:00:00:01",
                "ge-0/0/1": "aa:00:00:00:00:03",
            },
        }

        baseline = _snap(
            devices={"gw1": gw, "sw1": sw_up, "sw2": sw_down_base},
            networks=networks,
            port_usages=port_usages,
            lldp_neighbors=lldp,
        )
        predicted = _snap(
            devices={"gw1": gw, "sw1": sw_up, "sw2": sw_down_pred},
            networks=networks,
            port_usages=port_usages,
            lldp_neighbors=lldp,
        )

        results = check_connectivity(baseline, predicted)
        path = next(r for r in results if r.check_id == "CONN-VLAN-PATH")

        assert path.status == "error"
        assert any("sw-down" in d and "VLAN 10" in d for d in path.details)

    def test_detects_vlan_path_loss_without_gateway_anchor(self):
        """Even without a gateway node in the VLAN graph, dropping VLAN carriage
        on an existing LLDP link should be flagged by CONN-VLAN-PATH.
        """
        networks = {
            "net-mgmt": {"name": "mgmt", "vlan_id": 10},
            "net-data": {"name": "data", "vlan_id": 20},
        }
        port_usages = {
            "uplink": {"mode": "trunk", "all_networks": True},
            "mgmt-only": {"mode": "access", "port_network": "mgmt", "vlan_id": 10},
        }

        sw_a_base = _dev(
            "sw-a",
            "aa:00:00:00:00:11",
            "US-NY-SWA-01",
            "switch",
            port_config={"ge-0/0/1": {"usage": "uplink"}},
        )
        sw_a_pred = _dev(
            "sw-a",
            "aa:00:00:00:00:11",
            "US-NY-SWA-01",
            "switch",
            port_config={"ge-0/0/1": {"usage": "mgmt-only"}},
        )
        sw_c = _dev(
            "sw-c",
            "aa:00:00:00:00:12",
            "US-NY-SWC-01",
            "switch",
            port_config={"ge-0/0/1": {"usage": "uplink"}},
        )

        lldp = {
            "aa:00:00:00:00:11": {"ge-0/0/1": "aa:00:00:00:00:12"},
            "aa:00:00:00:00:12": {"ge-0/0/1": "aa:00:00:00:00:11"},
        }

        baseline = _snap(
            devices={"sw-a": sw_a_base, "sw-c": sw_c},
            networks=networks,
            port_usages=port_usages,
            lldp_neighbors=lldp,
        )
        predicted = _snap(
            devices={"sw-a": sw_a_pred, "sw-c": sw_c},
            networks=networks,
            port_usages=port_usages,
            lldp_neighbors=lldp,
        )

        results = check_connectivity(baseline, predicted)
        path = next(r for r in results if r.check_id == "CONN-VLAN-PATH")

        assert path.status == "error"
        assert any("lost L2 path" in d and "VLAN 20" in d for d in path.details)
        assert "sw-a" in path.affected_objects
        assert "sw-c" in path.affected_objects


# ---------------------------------------------------------------------------
# TestCheckDescriptions
# ---------------------------------------------------------------------------


class TestCheckDescriptions:
    """Verify connectivity checks populate the description field."""

    def test_conn_phys_description_populated(self):
        """CONN-PHYS populates description on pass and fail paths."""
        snap = _snap()
        results = check_connectivity(snap, snap)
        conn_phys = next(r for r in results if r.check_id == "CONN-PHYS")
        assert conn_phys.description != ""

    def test_conn_vlan_description_populated(self):
        """CONN-VLAN populates description on pass path."""
        snap = _snap()
        results = check_connectivity(snap, snap)
        conn_vlan = next(r for r in results if r.check_id == "CONN-VLAN")
        assert conn_vlan.description != ""

    def test_conn_vlan_path_description_populated(self):
        """CONN-VLAN-PATH populates description on pass path."""
        snap = _snap()
        results = check_connectivity(snap, snap)
        conn_path = next(r for r in results if r.check_id == "CONN-VLAN-PATH")
        assert conn_path.description != ""

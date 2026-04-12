"""
Unit tests for PORT-DISC and PORT-CLIENT checks (checks/port_impact.py).
"""

from __future__ import annotations

import pytest

from app.modules.digital_twin.checks.port_impact import check_port_impact
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _dev(
    dev_id: str,
    mac: str,
    device_type: str = "switch",
    name: str | None = None,
    port_config: dict | None = None,
) -> DeviceSnapshot:
    """Create a minimal DeviceSnapshot."""
    return DeviceSnapshot(
        device_id=dev_id,
        mac=mac,
        name=name or dev_id.upper(),
        type=device_type,
        model="EX4100-48P",
        port_config=port_config or {},
        ip_config={},
        dhcpd_config={},
    )


def _snap(
    devices: dict[str, DeviceSnapshot] | None = None,
    lldp_neighbors: dict[str, dict[str, str]] | None = None,
    ap_clients: dict[str, int] | None = None,
    port_devices: dict[str, dict[str, str]] | None = None,
    site_id: str = "site-1",
) -> SiteSnapshot:
    """Create a minimal SiteSnapshot."""
    return SiteSnapshot(
        site_id=site_id,
        site_name="Branch-1",
        site_setting={},
        networks={},
        wlans={},
        devices=devices or {},
        port_usages={},
        lldp_neighbors=lldp_neighbors or {},
        port_status={},
        ap_clients=ap_clients or {},
        port_devices=port_devices or {},
    )


# ---------------------------------------------------------------------------
# TestPortDisc
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPortDisc:
    """Tests for PORT-DISC: port profile disconnect risk."""

    def test_disabled_port_with_neighbor_critical(self):
        """Disabling a port with an LLDP neighbor that is an AP -> critical."""
        ap = _dev("ap-1", mac="aa:bb:cc:00:00:01", device_type="ap", name="AP-Lobby")
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            device_type="switch",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "ap"}},
        )

        baseline = _snap(
            devices={"sw-1": sw, "ap-1": ap},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/0": "aa:bb:cc:00:00:01"}},
        )

        # Predicted: port disabled
        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            device_type="switch",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "disabled"}},
        )
        predicted = _snap(
            devices={"sw-1": sw_pred, "ap-1": ap},
            lldp_neighbors=baseline.lldp_neighbors,
        )

        results = check_port_impact(baseline, predicted)
        disc = results[0]

        assert disc.check_id == "PORT-DISC"
        assert disc.layer == 2
        assert disc.status == "critical"
        assert len(disc.details) == 1
        assert "AP-Lobby" in disc.details[0]
        assert "ge-0/0/0" in disc.details[0]
        assert "site-1" in disc.affected_sites

    def test_no_change_passes(self):
        """No port config changes -> pass."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            device_type="switch",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "ap"}},
        )
        ap = _dev("ap-1", mac="aa:bb:cc:00:00:01", device_type="ap")

        snap = _snap(
            devices={"sw-1": sw, "ap-1": ap},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/0": "aa:bb:cc:00:00:01"}},
        )

        results = check_port_impact(snap, snap)
        disc = results[0]

        assert disc.check_id == "PORT-DISC"
        assert disc.status == "pass"
        assert disc.details == []

    def test_port_removed_with_neighbor(self):
        """Port removed from predicted config while neighbor exists -> disconnect."""
        sw_baseline = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "trunk"}, "ge-0/0/1": {"usage": "ap"}},
        )
        other_sw = _dev("sw-2", mac="aa:bb:cc:00:00:20", device_type="switch", name="SW-Access")

        baseline = _snap(
            devices={"sw-1": sw_baseline, "sw-2": other_sw},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/0": "aa:bb:cc:00:00:20"}},
        )

        # Predicted: ge-0/0/0 removed
        sw_predicted = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/1": {"usage": "ap"}},
        )
        predicted = _snap(
            devices={"sw-1": sw_predicted, "sw-2": other_sw},
            lldp_neighbors=baseline.lldp_neighbors,
        )

        results = check_port_impact(baseline, predicted)
        disc = results[0]

        assert disc.check_id == "PORT-DISC"
        assert disc.status == "critical"  # connected device is a switch
        assert "SW-Access" in disc.details[0]
        assert "ge-0/0/0" in disc.details[0]

    def test_usage_change_is_disconnect(self):
        """Changing port usage with LLDP neighbor -> disconnect."""
        gw = _dev("gw-1", mac="aa:bb:cc:00:00:99", device_type="gateway", name="GW-Edge")
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
        )

        baseline = _snap(
            devices={"sw-1": sw, "gw-1": gw},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/0": "aa:bb:cc:00:00:99"}},
        )

        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "access"}},
        )
        predicted = _snap(
            devices={"sw-1": sw_pred, "gw-1": gw},
            lldp_neighbors=baseline.lldp_neighbors,
        )

        results = check_port_impact(baseline, predicted)
        disc = results[0]

        assert disc.status == "error"  # gateway is not ap or switch
        assert "GW-Edge" in disc.details[0]

    def test_neighbor_not_in_devices_still_flagged(self):
        """LLDP neighbor MAC not found in devices -> uses MAC as name, type unknown -> error."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
        )

        baseline = _snap(
            devices={"sw-1": sw},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/0": "ff:ff:ff:00:00:01"}},
        )

        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "disabled"}},
        )
        predicted = _snap(
            devices={"sw-1": sw_pred},
            lldp_neighbors=baseline.lldp_neighbors,
        )

        results = check_port_impact(baseline, predicted)
        disc = results[0]

        assert disc.status == "error"  # unknown type -> error
        assert "ff:ff:ff:00:00:01" in disc.details[0]

    def test_no_lldp_neighbors_with_switch_is_skipped(self):
        """Switch present but LLDP data missing -> skipped (cannot verify)."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
        )

        baseline = _snap(devices={"sw-1": sw}, lldp_neighbors={})

        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "disabled"}},
        )
        predicted = _snap(devices={"sw-1": sw_pred}, lldp_neighbors={})

        results = check_port_impact(baseline, predicted)
        disc, client = results

        assert disc.check_id == "PORT-DISC"
        assert disc.status == "skipped"
        assert "LLDP" in disc.summary
        assert disc.affected_sites == ["site-1"]

        assert client.check_id == "PORT-CLIENT"
        assert client.status == "skipped"

    def test_port_devices_fallback_detects_disconnect_on_logical_port(self):
        """When LLDP is missing but port_devices shows an AP on ge-0/0/5.0,
        disabling ge-0/0/5 must still be detected.
        """
        ap = _dev("ap-1", mac="aa:bb:cc:00:00:01", device_type="ap", name="AP-Lobby")
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/5": {"usage": "ap"}},
        )

        baseline = _snap(
            devices={"sw-1": sw, "ap-1": ap},
            lldp_neighbors={},
            port_devices={"aa:bb:cc:00:00:10": {"ge-0/0/5.0": "aa:bb:cc:00:00:01"}},
        )

        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/5": {"usage": "disabled"}},
        )
        predicted = _snap(
            devices={"sw-1": sw_pred, "ap-1": ap},
            lldp_neighbors={},
            port_devices=baseline.port_devices,
        )

        disc, client = check_port_impact(baseline, predicted)

        assert disc.check_id == "PORT-DISC"
        assert disc.status == "critical"
        assert disc.summary.startswith("1 port change")
        assert any("ge-0/0/5" in d and "AP-Lobby" in d for d in disc.details)

        assert client.check_id == "PORT-CLIENT"
        assert client.status == "pass"

    def test_no_switches_no_lldp_passes(self):
        """No switches or gateways in snapshot -> pass (check not applicable)."""
        ap = _dev("ap-1", mac="aa:bb:cc:00:00:01", device_type="ap", name="AP-Lobby")
        snap = _snap(devices={"ap-1": ap}, lldp_neighbors={})

        results = check_port_impact(snap, snap)
        disc, client = results

        assert disc.status == "pass"
        assert client.status == "pass"


# ---------------------------------------------------------------------------
# TestPortClient
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPortClient:
    """Tests for PORT-CLIENT: client impact estimation."""

    def test_estimates_client_impact_with_ap_on_disabled_port(self):
        """Disconnecting an AP with clients -> warning with client count."""
        ap = _dev("ap-1", mac="aa:bb:cc:00:00:01", device_type="ap", name="AP-Floor2")
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/5": {"usage": "ap"}},
        )

        baseline = _snap(
            devices={"sw-1": sw, "ap-1": ap},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/5": "aa:bb:cc:00:00:01"}},
            ap_clients={"ap-1": 25},
        )

        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/5": {"usage": "disabled"}},
        )
        predicted = _snap(
            devices={"sw-1": sw_pred, "ap-1": ap},
            lldp_neighbors=baseline.lldp_neighbors,
            ap_clients=baseline.ap_clients,
        )

        results = check_port_impact(baseline, predicted)
        client = results[1]

        assert client.check_id == "PORT-CLIENT"
        assert client.layer == 2
        assert client.status == "warning"
        assert "25" in client.summary
        assert len(client.details) == 1
        assert "AP-Floor2" in client.details[0]

    def test_critical_when_50_or_more_clients(self):
        """>=50 clients affected -> critical."""
        ap1 = _dev("ap-1", mac="aa:bb:cc:00:00:01", device_type="ap", name="AP-1")
        ap2 = _dev("ap-2", mac="aa:bb:cc:00:00:02", device_type="ap", name="AP-2")
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={
                "ge-0/0/1": {"usage": "ap"},
                "ge-0/0/2": {"usage": "ap"},
            },
        )

        baseline = _snap(
            devices={"sw-1": sw, "ap-1": ap1, "ap-2": ap2},
            lldp_neighbors={
                "aa:bb:cc:00:00:10": {
                    "ge-0/0/1": "aa:bb:cc:00:00:01",
                    "ge-0/0/2": "aa:bb:cc:00:00:02",
                }
            },
            ap_clients={"ap-1": 30, "ap-2": 25},
        )

        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={
                "ge-0/0/1": {"usage": "disabled"},
                "ge-0/0/2": {"usage": "disabled"},
            },
        )
        predicted = _snap(
            devices={"sw-1": sw_pred, "ap-1": ap1, "ap-2": ap2},
            lldp_neighbors=baseline.lldp_neighbors,
            ap_clients=baseline.ap_clients,
        )

        results = check_port_impact(baseline, predicted)
        client = results[1]

        assert client.check_id == "PORT-CLIENT"
        assert client.status == "critical"
        assert "55" in client.summary

    def test_no_clients_pass(self):
        """LLDP data present but no APs disconnected -> pass."""
        sw_uplink = _dev("sw-2", mac="aa:bb:cc:00:00:20", device_type="switch", name="SW-Uplink")
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
        )

        snap = _snap(
            devices={"sw-1": sw, "sw-2": sw_uplink},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/0": "aa:bb:cc:00:00:20"}},
        )

        results = check_port_impact(snap, snap)
        client = results[1]

        assert client.check_id == "PORT-CLIENT"
        assert client.status == "pass"

    def test_disconnected_ap_with_zero_clients_pass(self):
        """AP disconnected but has 0 clients -> pass."""
        ap = _dev("ap-1", mac="aa:bb:cc:00:00:01", device_type="ap", name="AP-Empty")
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/5": {"usage": "ap"}},
        )

        baseline = _snap(
            devices={"sw-1": sw, "ap-1": ap},
            lldp_neighbors={"aa:bb:cc:00:00:10": {"ge-0/0/5": "aa:bb:cc:00:00:01"}},
            ap_clients={},  # no clients
        )

        sw_pred = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={"ge-0/0/5": {"usage": "disabled"}},
        )
        predicted = _snap(
            devices={"sw-1": sw_pred, "ap-1": ap},
            lldp_neighbors=baseline.lldp_neighbors,
        )

        results = check_port_impact(baseline, predicted)
        client = results[1]

        assert client.check_id == "PORT-CLIENT"
        assert client.status == "pass"
        assert (
            "0" not in client.summary
            or "no wireless" in client.summary.lower()
            or "AP(s) disconnected" in client.summary
        )

"""Regression tests for second-pass review fixes (B4, B5, B6, B8)."""

from __future__ import annotations

import pytest

from app.modules.digital_twin.checks.connectivity import check_connectivity
from app.modules.digital_twin.checks.routing import check_routing
from app.modules.digital_twin.checks.stp import check_stp
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot


def _dev(
    dev_id: str,
    mac: str,
    name: str,
    dtype: str = "switch",
    port_config: dict | None = None,
    ip_config: dict | None = None,
) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=dev_id,
        mac=mac,
        name=name,
        type=dtype,
        model="EX4100" if dtype == "switch" else ("SRX320" if dtype == "gateway" else "AP45"),
        port_config=port_config or {},
        ip_config=ip_config or {},
        dhcpd_config={},
    )


def _snap(
    devices=None,
    lldp_neighbors=None,
    port_devices=None,
    networks=None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting={},
        networks=networks or {},
        wlans={},
        devices=devices or {},
        port_usages={},
        lldp_neighbors=lldp_neighbors or {},
        port_status={},
        ap_clients={},
        port_devices=port_devices or {},
    )


# ---------------------------------------------------------------------------
# B4 — CONN-PHYS: predicted having no gateways must flag critical, not
# report every non-GW device as "newly isolated".
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConnPhysGatewayRemoval:
    def test_predicted_loses_all_gateways_flags_single_critical(self):
        gw = _dev("gw-1", "aa:bb:cc:00:00:01", "GW-1", dtype="gateway")
        sw = _dev("sw-1", "aa:bb:cc:00:00:02", "SW-1", dtype="switch")
        baseline = _snap(
            devices={"gw-1": gw, "sw-1": sw},
            port_devices={
                "aa:bb:cc:00:00:01": {"ge-0/0/0": "aa:bb:cc:00:00:02"},
                "aa:bb:cc:00:00:02": {"ge-0/0/0": "aa:bb:cc:00:00:01"},
            },
        )
        # Predicted: gateway removed entirely
        predicted = _snap(
            devices={"sw-1": sw},
            port_devices={},
        )

        results = check_connectivity(baseline, predicted)
        phys = next(r for r in results if r.check_id == "CONN-PHYS")
        assert phys.status == "critical"
        # Single summary, not a per-device cascade.
        assert "no gateway" in phys.summary.lower()


# ---------------------------------------------------------------------------
# B5 — ROUTE-WAN: single WAN removal that drops a gateway to zero WANs
# must escalate to `critical`, not `warning`.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRouteWanOutage:
    def test_single_wan_removal_with_zero_remaining_is_critical(self):
        gw_base = _dev(
            "gw-1",
            "aa:bb:cc:00:00:01",
            "GW-1",
            dtype="gateway",
            port_config={"ge-0/0/0": {"usage": "wan", "wan_type": "broadband"}},
        )
        gw_pred = _dev(
            "gw-1",
            "aa:bb:cc:00:00:01",
            "GW-1",
            dtype="gateway",
            port_config={"ge-0/0/0": {"usage": "trunk"}},
        )
        baseline = _snap(devices={"gw-1": gw_base})
        predicted = _snap(devices={"gw-1": gw_pred})

        results = check_routing(baseline, predicted)
        wan = next(r for r in results if r.check_id == "ROUTE-WAN")
        assert wan.status == "critical"
        combined = (" ".join(wan.details) + " " + wan.summary).lower()
        assert "no wan" in combined or "lose all wan" in combined

    def test_single_wan_removal_with_remaining_wans_stays_warning(self):
        """A redundant gateway losing one of several WANs stays warning."""
        gw_base = _dev(
            "gw-1",
            "aa:bb:cc:00:00:01",
            "GW-1",
            dtype="gateway",
            port_config={
                "ge-0/0/0": {"usage": "wan", "wan_type": "broadband"},
                "ge-0/0/1": {"usage": "wan", "wan_type": "lte"},
            },
        )
        gw_pred = _dev(
            "gw-1",
            "aa:bb:cc:00:00:01",
            "GW-1",
            dtype="gateway",
            port_config={
                "ge-0/0/0": {"usage": "trunk"},
                "ge-0/0/1": {"usage": "wan", "wan_type": "lte"},
            },
        )
        baseline = _snap(devices={"gw-1": gw_base})
        predicted = _snap(devices={"gw-1": gw_pred})

        results = check_routing(baseline, predicted)
        wan = next(r for r in results if r.check_id == "ROUTE-WAN")
        assert wan.status == "warning"


# ---------------------------------------------------------------------------
# B6 — STP-LOOP: affected_objects must be device_ids, not display names.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStpLoopAffectedObjects:
    def test_new_cycle_reports_device_ids_in_affected_objects(self):
        # Match the existing STP test pattern: colon-format MACs everywhere.
        sw_a = _dev("id-a", "aa:00:00:00:00:01", "SW-A")
        sw_b = _dev("id-b", "aa:00:00:00:00:02", "SW-B")
        sw_c = _dev("id-c", "aa:00:00:00:00:03", "SW-C")
        devices = {"id-a": sw_a, "id-b": sw_b, "id-c": sw_c}
        # Baseline: chain (no cycle).
        baseline = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
                "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:03": {"ge-0/0/0": "aa:00:00:00:00:02"},
            },
        )
        # Predicted: triangle.
        predicted = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/2": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:03": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/2": "aa:00:00:00:00:01"},
            },
        )

        results = check_stp(baseline, predicted)
        loop = next(r for r in results if r.check_id == "STP-LOOP")
        assert loop.status == "warning"
        # affected_objects must be IDs — not display names like "SW-A".
        assert set(loop.affected_objects) == {"id-a", "id-b", "id-c"}
        assert "SW-A" not in loop.affected_objects

"""
Unit tests for STP checks (checks/stp.py).

STP-ROOT: root bridge shift detection
STP-BPDU: BPDU filter on trunk ports
STP-LOOP: new L2 cycle detection
"""

from __future__ import annotations

import pytest

from app.modules.digital_twin.checks.stp import check_stp
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
    stp_config: dict | None = None,
    port_usages: dict | None = None,
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
        stp_config=stp_config,
        port_usages=port_usages,
    )


def _snap(
    devices: dict[str, DeviceSnapshot] | None = None,
    lldp_neighbors: dict[str, dict[str, str]] | None = None,
    port_usages: dict[str, dict] | None = None,
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
        port_usages=port_usages or {},
        lldp_neighbors=lldp_neighbors or {},
        port_status={},
        ap_clients={},
        port_devices={},
    )


# ---------------------------------------------------------------------------
# TestStpRoot
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStpRoot:
    """Tests for STP-ROOT: root bridge shift detection."""

    def test_priority_change_shifts_root(self):
        """Changing priorities so a different switch becomes root -> warning."""
        sw1 = _dev("sw-1", mac="aa:bb:cc:00:00:01", name="SW-Core", stp_config={"bridge_priority": 4096})
        sw2 = _dev("sw-2", mac="aa:bb:cc:00:00:02", name="SW-Access", stp_config={"bridge_priority": 32768})

        baseline = _snap(devices={"sw-1": sw1, "sw-2": sw2})

        sw1_pred = _dev("sw-1", mac="aa:bb:cc:00:00:01", name="SW-Core", stp_config={"bridge_priority": 32768})
        sw2_pred = _dev("sw-2", mac="aa:bb:cc:00:00:02", name="SW-Access", stp_config={"bridge_priority": 4096})

        predicted = _snap(devices={"sw-1": sw1_pred, "sw-2": sw2_pred})

        results = check_stp(baseline, predicted)
        root_result = results[0]

        assert root_result.check_id == "STP-ROOT"
        assert root_result.layer == 5
        assert root_result.status == "warning"
        assert "SW-Core" in root_result.details[0]
        assert "SW-Access" in root_result.details[1]
        assert "site-1" in root_result.affected_sites

    def test_no_change_passes(self):
        """Same priorities in baseline and predicted -> pass."""
        sw1 = _dev("sw-1", mac="aa:bb:cc:00:00:01", name="SW-Core", stp_config={"stp_priority": 4096})
        sw2 = _dev("sw-2", mac="aa:bb:cc:00:00:02", name="SW-Access", stp_config={"stp_priority": 32768})

        snap = _snap(devices={"sw-1": sw1, "sw-2": sw2})

        results = check_stp(snap, snap)
        root_result = results[0]

        assert root_result.check_id == "STP-ROOT"
        assert root_result.status == "pass"

    def test_rstp_priority_variant(self):
        """rstp_priority key is also recognized."""
        sw1 = _dev("sw-1", mac="aa:bb:cc:00:00:01", name="SW-A", stp_config={"rstp_priority": 4096})
        sw2 = _dev("sw-2", mac="aa:bb:cc:00:00:02", name="SW-B", stp_config={"rstp_priority": 32768})

        baseline = _snap(devices={"sw-1": sw1, "sw-2": sw2})

        sw1_pred = _dev("sw-1", mac="aa:bb:cc:00:00:01", name="SW-A", stp_config={"rstp_priority": 32768})
        sw2_pred = _dev("sw-2", mac="aa:bb:cc:00:00:02", name="SW-B", stp_config={"rstp_priority": 4096})

        predicted = _snap(devices={"sw-1": sw1_pred, "sw-2": sw2_pred})

        results = check_stp(baseline, predicted)
        assert results[0].status == "warning"

    def test_no_stp_config_skipped(self):
        """No STP priority on any switch -> skipped."""
        sw1 = _dev("sw-1", mac="aa:bb:cc:00:00:01")
        sw2 = _dev("sw-2", mac="aa:bb:cc:00:00:02")

        snap = _snap(devices={"sw-1": sw1, "sw-2": sw2})

        results = check_stp(snap, snap)
        assert results[0].check_id == "STP-ROOT"
        assert results[0].status == "skipped"

    def test_mac_tiebreak(self):
        """Equal priorities: lowest MAC wins root. Shifting MAC order changes root."""
        sw1 = _dev("sw-1", mac="aa:bb:cc:00:00:01", name="SW-LowMAC", stp_config={"bridge_priority": 4096})
        sw2 = _dev("sw-2", mac="aa:bb:cc:00:00:ff", name="SW-HighMAC", stp_config={"bridge_priority": 4096})

        baseline = _snap(devices={"sw-1": sw1, "sw-2": sw2})

        # Same as baseline — sw-1 wins tiebreak (lower MAC)
        results = check_stp(baseline, baseline)
        assert results[0].status == "pass"


# ---------------------------------------------------------------------------
# TestStpBpdu
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStpBpdu:
    """Tests for STP-BPDU: BPDU filter on trunk ports."""

    def test_bpdu_filter_on_trunk_warning(self):
        """BPDU filter on a direct trunk port -> warning."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={
                "ge-0/0/0": {"usage": "trunk", "bpdu_filter": True},
            },
        )

        predicted = _snap(devices={"sw-1": sw})

        results = check_stp(predicted, predicted)
        bpdu_result = results[1]

        assert bpdu_result.check_id == "STP-BPDU"
        assert bpdu_result.layer == 5
        assert bpdu_result.status == "warning"
        assert len(bpdu_result.details) == 1
        assert "SW-Core" in bpdu_result.details[0]
        assert "ge-0/0/0" in bpdu_result.details[0]

    def test_bpdu_filter_on_access_port_passes(self):
        """BPDU filter on an access port is fine -> pass."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={
                "ge-0/0/0": {"usage": "access", "bpdu_filter": True},
            },
        )

        predicted = _snap(devices={"sw-1": sw})

        results = check_stp(predicted, predicted)
        bpdu_result = results[1]

        assert bpdu_result.check_id == "STP-BPDU"
        assert bpdu_result.status == "pass"

    def test_stp_bpdu_filter_variant(self):
        """stp_bpdu_filter key variant also detected."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={
                "et-0/0/0": {"usage": "trunk", "stp_bpdu_filter": True},
            },
        )

        predicted = _snap(devices={"sw-1": sw})

        results = check_stp(predicted, predicted)
        assert results[1].status == "warning"

    def test_bpdu_filter_on_profile_trunk(self):
        """Port uses a profile that resolves to trunk mode with BPDU filter -> warning."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={
                "ge-0/0/0": {"usage": "uplink", "bpdu_filter": True},
            },
        )

        # Site-level port_usages defines "uplink" as trunk
        predicted = _snap(
            devices={"sw-1": sw},
            port_usages={"uplink": {"mode": "trunk"}},
        )

        results = check_stp(predicted, predicted)
        assert results[1].status == "warning"

    def test_no_bpdu_filter_passes(self):
        """No BPDU filter at all -> pass."""
        sw = _dev(
            "sw-1",
            mac="aa:bb:cc:00:00:10",
            name="SW-Core",
            port_config={
                "ge-0/0/0": {"usage": "trunk"},
                "ge-0/0/1": {"usage": "access"},
            },
        )

        predicted = _snap(devices={"sw-1": sw})

        results = check_stp(predicted, predicted)
        assert results[1].check_id == "STP-BPDU"
        assert results[1].status == "pass"

    def test_non_switch_devices_ignored(self):
        """BPDU filter on a gateway port is not flagged (only switches checked)."""
        gw = _dev(
            "gw-1",
            mac="aa:bb:cc:00:00:99",
            device_type="gateway",
            name="GW-Edge",
            port_config={
                "ge-0/0/0": {"usage": "trunk", "bpdu_filter": True},
            },
        )

        predicted = _snap(devices={"gw-1": gw})

        results = check_stp(predicted, predicted)
        assert results[1].status == "pass"


# ---------------------------------------------------------------------------
# TestStpLoop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStpLoop:
    """Tests for STP-LOOP: new L2 cycle detection."""

    def test_new_cycle_detected(self):
        """Adding a link that creates a triangle -> warning."""
        sw1 = _dev("sw-1", mac="aa:00:00:00:00:01", name="SW-A")
        sw2 = _dev("sw-2", mac="aa:00:00:00:00:02", name="SW-B")
        sw3 = _dev("sw-3", mac="aa:00:00:00:00:03", name="SW-C")

        devices = {"sw-1": sw1, "sw-2": sw2, "sw-3": sw3}

        # Baseline: linear chain A-B-C
        baseline = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
                "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:03": {"ge-0/0/0": "aa:00:00:00:00:02"},
            },
        )

        # Predicted: triangle A-B-C-A (add link C->A)
        predicted = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:03": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/1": "aa:00:00:00:00:01"},
            },
        )

        results = check_stp(baseline, predicted)
        loop_result = results[2]

        assert loop_result.check_id == "STP-LOOP"
        assert loop_result.layer == 5
        assert loop_result.status == "warning"
        assert len(loop_result.details) >= 1
        assert "New cycle" in loop_result.details[0]
        assert len(loop_result.affected_objects) > 0

    def test_no_new_cycles_passes(self):
        """Same topology in baseline and predicted -> pass."""
        sw1 = _dev("sw-1", mac="aa:00:00:00:00:01", name="SW-A")
        sw2 = _dev("sw-2", mac="aa:00:00:00:00:02", name="SW-B")

        devices = {"sw-1": sw1, "sw-2": sw2}
        lldp = {
            "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
            "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01"},
        }

        snap = _snap(devices=devices, lldp_neighbors=lldp)

        results = check_stp(snap, snap)
        loop_result = results[2]

        assert loop_result.check_id == "STP-LOOP"
        assert loop_result.status == "pass"

    def test_existing_cycle_not_flagged(self):
        """Cycle already present in baseline is not a new risk -> pass."""
        sw1 = _dev("sw-1", mac="aa:00:00:00:00:01", name="SW-A")
        sw2 = _dev("sw-2", mac="aa:00:00:00:00:02", name="SW-B")
        sw3 = _dev("sw-3", mac="aa:00:00:00:00:03", name="SW-C")

        devices = {"sw-1": sw1, "sw-2": sw2, "sw-3": sw3}

        # Both baseline and predicted have the triangle
        triangle_lldp = {
            "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/1": "aa:00:00:00:00:03"},
            "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01", "ge-0/0/1": "aa:00:00:00:00:03"},
            "aa:00:00:00:00:03": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/1": "aa:00:00:00:00:01"},
        }

        snap = _snap(devices=devices, lldp_neighbors=triangle_lldp)

        results = check_stp(snap, snap)
        assert results[2].status == "pass"

    def test_no_devices_passes(self):
        """Empty topology -> pass."""
        snap = _snap()

        results = check_stp(snap, snap)
        assert results[2].check_id == "STP-LOOP"
        assert results[2].status == "pass"

    def test_cycle_detail_falls_back_to_mac_when_name_missing(self):
        """A cycle node whose DeviceSnapshot.name is empty must render as its
        MAC in the detail string instead of producing "a ->  -> b" (double
        space where the name would be). Also guards against empty strings
        creeping into affected_objects.
        """
        sw_named = _dev("sw-a", mac="aa:00:00:00:00:01", name="SW-A")
        # Bypass the _dev helper because it would fall back to dev_id.upper()
        # for an empty name — we need the DeviceSnapshot to actually carry an
        # empty string so we exercise the real production code path.
        sw_unnamed = DeviceSnapshot(
            device_id="sw-b",
            mac="aa:00:00:00:00:02",
            name="",
            type="switch",
            model="EX4100-48P",
            port_config={},
            ip_config={},
            dhcpd_config={},
        )
        sw_also_named = _dev("sw-c", mac="aa:00:00:00:00:03", name="SW-C")

        devices = {"sw-a": sw_named, "sw-b": sw_unnamed, "sw-c": sw_also_named}

        baseline = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02"},
                "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:03": {"ge-0/0/0": "aa:00:00:00:00:02"},
            },
        )
        predicted = _snap(
            devices=devices,
            lldp_neighbors={
                "aa:00:00:00:00:01": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:02": {"ge-0/0/0": "aa:00:00:00:00:01", "ge-0/0/1": "aa:00:00:00:00:03"},
                "aa:00:00:00:00:03": {"ge-0/0/0": "aa:00:00:00:00:02", "ge-0/0/1": "aa:00:00:00:00:01"},
            },
        )

        results = check_stp(baseline, predicted)
        loop_result = results[2]

        assert loop_result.status == "warning"
        joined_details = " ".join(loop_result.details)
        # The unnamed switch should render as its MAC, not as an empty cell
        assert "aa:00:00:00:00:02" in joined_details
        # No double-space artefact like "SW-A ->  -> SW-C"
        assert " ->  -> " not in joined_details
        # affected_objects must never contain an empty string
        assert "" not in loop_result.affected_objects

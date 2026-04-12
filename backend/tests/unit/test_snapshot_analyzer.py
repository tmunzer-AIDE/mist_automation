"""
Unit tests for snapshot_analyzer: analyze_site() and build_prediction_report().
"""

from __future__ import annotations

from app.modules.digital_twin.models import CheckResult, PredictionReport
from app.modules.digital_twin.services.site_snapshot import DeviceSnapshot, SiteSnapshot
from app.modules.digital_twin.services.snapshot_analyzer import (
    analyze_site,
    build_prediction_report,
    compute_overall_severity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dev(dev_id: str, mac: str, name: str, dtype: str = "switch", **kw) -> DeviceSnapshot:
    return DeviceSnapshot(
        device_id=dev_id,
        mac=mac,
        name=name,
        type=dtype,
        model="EX4100" if dtype == "switch" else "SRX320",
        port_config=kw.get("port_config", {}),
        ip_config=kw.get("ip_config", {}),
        dhcpd_config=kw.get("dhcpd_config", {}),
        oob_ip_config=kw.get("oob_ip_config"),
        port_usages=kw.get("port_usages"),
        ospf_config=kw.get("ospf_config"),
        bgp_config=kw.get("bgp_config"),
        extra_routes=kw.get("extra_routes"),
        stp_config=kw.get("stp_config"),
    )


def _snap(
    devices=None,
    lldp=None,
    networks=None,
    wlans=None,
    port_usages=None,
    site_setting=None,
    ap_clients=None,
    port_status=None,
    port_devices=None,
    ospf_peers=None,
    bgp_peers=None,
) -> SiteSnapshot:
    return SiteSnapshot(
        site_id="site-1",
        site_name="Test Site",
        site_setting=site_setting or {},
        networks=networks or {},
        wlans=wlans or {},
        devices=devices or {},
        port_usages=port_usages or {},
        lldp_neighbors=lldp or {},
        port_status=port_status or {},
        ap_clients=ap_clients or {},
        port_devices=port_devices or {},
        ospf_peers=ospf_peers or {},
        bgp_peers=bgp_peers or {},
    )


def _get_result(results: list[CheckResult], check_id: str) -> CheckResult | None:
    """Extract a specific check result by check_id."""
    for r in results:
        if r.check_id == check_id:
            return r
    return None


def _result(
    check_id: str,
    status: str,
    pre_existing: bool = False,
    details: list[str] | None = None,
) -> CheckResult:
    """Create a minimal CheckResult with given id and status."""
    return CheckResult(
        check_id=check_id,
        check_name=f"Test {check_id}",
        layer=1,
        status=status,
        summary=f"{check_id} {status}",
        details=details or [],
        pre_existing=pre_existing,
    )


# ---------------------------------------------------------------------------
# test_analyze_site_runs_all_categories
# ---------------------------------------------------------------------------


class TestAnalyzeSite:
    def test_runs_all_categories(self):
        """Build a snapshot with a switch + gateway, call analyze_site(snap, snap),
        and verify all expected check_ids are present."""
        sw = _dev("sw-1", "aa:bb:cc:dd:ee:01", "core-sw-1", dtype="switch")
        gw = _dev(
            "gw-1",
            "aa:bb:cc:dd:ee:02",
            "gw-1",
            dtype="gateway",
            ip_config={"mgmt": {"ip": "10.0.0.1", "netmask": "255.255.255.0"}},
        )

        snap = _snap(
            devices={"sw-1": sw, "gw-1": gw},
            networks={"net-1": {"name": "mgmt", "vlan_id": 10, "subnet": "10.0.0.0/24"}},
            lldp={"aa:bb:cc:dd:ee:01": {"ge-0/0/0": "aa:bb:cc:dd:ee:02"}},
        )

        results = analyze_site(snap, snap)

        # Collect all check_ids
        check_ids = {r.check_id for r in results}

        # Connectivity (2)
        assert "CONN-PHYS" in check_ids
        assert "CONN-VLAN" in check_ids

        # Config conflicts (5)
        assert "CFG-SUBNET" in check_ids
        assert "CFG-VLAN" in check_ids
        assert "CFG-SSID" in check_ids
        assert "CFG-DHCP-RNG" in check_ids
        assert "CFG-DHCP-CFG" in check_ids

        # Template variables (1)
        assert "TMPL-VAR" in check_ids

        # Port impact (2)
        assert "PORT-DISC" in check_ids
        assert "PORT-CLIENT" in check_ids

        # Routing (4)
        assert "ROUTE-GW" in check_ids
        assert "ROUTE-OSPF" in check_ids
        assert "ROUTE-BGP" in check_ids
        assert "ROUTE-WAN" in check_ids

        # Security (3)
        assert "SEC-GUEST" in check_ids
        assert "SEC-POLICY" in check_ids
        assert "SEC-NAC" in check_ids

        # STP (3)
        assert "STP-ROOT" in check_ids
        assert "STP-BPDU" in check_ids
        assert "STP-LOOP" in check_ids

        # Total: 2 + 5 + 1 + 2 + 4 + 3 + 3 = 20
        assert len(results) == 20

    def test_baseline_equals_predicted_mostly_pass(self):
        """When baseline == predicted, most checks should pass or be skipped."""
        sw = _dev("sw-1", "aa:bb:cc:dd:ee:01", "core-sw-1", dtype="switch")
        snap = _snap(devices={"sw-1": sw})

        results = analyze_site(snap, snap)

        non_pass = [r for r in results if r.status not in ("pass", "skipped")]
        # With a minimal snapshot (no gateways, no networks) some checks may flag issues
        # (e.g. ROUTE-GW might pass because no networks), but no critical/error expected
        # from an identical baseline/predicted pair with clean data
        assert all(r.status in ("pass", "skipped", "warning", "info") for r in non_pass)

    def test_preexisting_subnet_overlap_marked(self):
        """Baseline already has a subnet overlap; predicted keeps it -> pre_existing."""
        # Two networks with the same subnet -> CFG-SUBNET critical in baseline.
        # The change under test only swaps a switch port config, so CFG-SUBNET
        # should be reported as pre_existing in the predicted results.
        sw_base = _dev(
            "sw-1",
            "aa:bb:cc:dd:ee:01",
            "core-sw-1",
            dtype="switch",
            port_config={"ge-0/0/9": {"usage": "ap"}},
        )
        sw_pred = _dev(
            "sw-1",
            "aa:bb:cc:dd:ee:01",
            "core-sw-1",
            dtype="switch",
            port_config={"ge-0/0/9": {"usage": "disabled"}},
        )

        networks = {
            "net-1": {"name": "DNT-E2E-DPLM", "vlan_id": 10, "subnet": "10.10.10.0/24"},
            "net-2": {"name": "PRD-MXE-data-0", "vlan_id": 20, "subnet": "10.10.10.0/24"},
        }

        baseline = _snap(devices={"sw-1": sw_base}, networks=networks)
        predicted = _snap(devices={"sw-1": sw_pred}, networks=networks)

        results = analyze_site(baseline, predicted)

        cfg = _get_result(results, "CFG-SUBNET")
        route = _get_result(results, "ROUTE-GW")

        assert cfg is not None
        assert cfg.status == "critical"
        assert cfg.pre_existing is True

        # ROUTE-GW also fails (no gateway device) but existed in baseline -> pre_existing.
        assert route is not None
        assert route.status == "error"
        assert route.pre_existing is True

        report = build_prediction_report(results)
        # Only pre-existing failures -> execution is not blocked by the simulation
        assert report.execution_safe is True

    def test_worsening_introduces_new_failure(self):
        """Predicted adds a NEW subnet overlap not present in baseline -> not pre_existing."""
        sw = _dev("sw-1", "aa:bb:cc:dd:ee:01", "core-sw-1", dtype="switch")

        baseline = _snap(
            devices={"sw-1": sw},
            networks={
                "net-1": {"name": "A", "vlan_id": 10, "subnet": "10.0.0.0/24"},
                "net-2": {"name": "B", "vlan_id": 20, "subnet": "10.1.0.0/24"},
            },
        )
        predicted = _snap(
            devices={"sw-1": sw},
            networks={
                "net-1": {"name": "A", "vlan_id": 10, "subnet": "10.0.0.0/24"},
                "net-2": {"name": "B", "vlan_id": 20, "subnet": "10.0.0.0/24"},  # new overlap
            },
        )

        results = analyze_site(baseline, predicted)
        cfg = _get_result(results, "CFG-SUBNET")

        assert cfg is not None
        assert cfg.status == "critical"
        assert cfg.pre_existing is False

        report = build_prediction_report(results)
        assert report.execution_safe is False


# ---------------------------------------------------------------------------
# test_build_prediction_report
# ---------------------------------------------------------------------------


class TestBuildPredictionReport:
    def test_mixed_statuses(self):
        """Create mixed status results, verify report counts and severity."""
        results = [
            _result("CHK-1", "pass"),
            _result("CHK-2", "pass"),
            _result("CHK-3", "warning"),
            _result("CHK-4", "error"),
            _result("CHK-5", "critical"),
            _result("CHK-6", "skipped"),
        ]

        report = build_prediction_report(results)

        assert isinstance(report, PredictionReport)
        assert report.passed == 2
        assert report.warnings == 1
        assert report.errors == 1
        assert report.critical == 1
        assert report.skipped == 1
        assert report.total_checks == 5  # 6 - 1 skipped
        assert report.overall_severity == "critical"
        assert report.execution_safe is False
        assert "1 critical" in report.summary
        assert "1 error(s)" in report.summary
        assert "1 warning(s)" in report.summary

    def test_all_pass(self):
        """All pass -> severity='clean', execution_safe=True."""
        results = [
            _result("CHK-1", "pass"),
            _result("CHK-2", "pass"),
            _result("CHK-3", "pass"),
        ]

        report = build_prediction_report(results)

        assert report.overall_severity == "clean"
        assert report.execution_safe is True
        assert report.summary == "All checks passed"
        assert report.passed == 3
        assert report.warnings == 0
        assert report.errors == 0
        assert report.critical == 0
        assert report.skipped == 0
        assert report.total_checks == 3

    def test_excludes_skipped_from_total(self):
        """Verify skipped checks don't count in total_checks."""
        results = [
            _result("CHK-1", "pass"),
            _result("CHK-2", "skipped"),
            _result("CHK-3", "skipped"),
            _result("CHK-4", "warning"),
        ]

        report = build_prediction_report(results)

        assert report.total_checks == 2  # 4 - 2 skipped
        assert report.skipped == 2
        assert report.passed == 1
        assert report.warnings == 1
        assert report.execution_safe is True  # no errors or critical

    def test_empty_results(self):
        """Empty results list produces a clean report."""
        report = build_prediction_report([])

        assert report.total_checks == 0
        assert report.passed == 0
        assert report.overall_severity == "clean"
        assert report.execution_safe is True
        assert report.summary == "All checks passed"

    def test_warnings_only_execution_safe(self):
        """Warnings do not block execution_safe."""
        results = [
            _result("CHK-1", "pass"),
            _result("CHK-2", "warning"),
            _result("CHK-3", "warning"),
        ]

        report = build_prediction_report(results)

        assert report.overall_severity == "warning"
        assert report.execution_safe is True
        assert "2 warning(s)" in report.summary

    def test_error_blocks_execution(self):
        """Error severity blocks execution_safe."""
        results = [
            _result("CHK-1", "pass"),
            _result("CHK-2", "error"),
        ]

        report = build_prediction_report(results)

        assert report.overall_severity == "error"
        assert report.execution_safe is False

    def test_pre_existing_errors_do_not_block_execution(self):
        """Failing checks flagged pre_existing are not introduced by the change and must not block."""
        results = [
            _result("CHK-1", "pass"),
            _result("CFG-SUBNET", "critical", pre_existing=True, details=["overlap A/B"]),
            _result("ROUTE-GW", "error", pre_existing=True, details=["missing gw"]),
        ]

        report = build_prediction_report(results)

        assert report.execution_safe is True
        assert report.critical == 1
        assert report.errors == 1
        assert report.overall_severity == "critical"
        assert "pre-existing" in report.summary

    def test_new_failure_still_blocks_even_with_preexisting(self):
        """A non-pre-existing failure still blocks, even alongside pre-existing ones."""
        results = [
            _result("CFG-SUBNET", "critical", pre_existing=True, details=["overlap A/B"]),
            _result("PORT-DISC", "critical", pre_existing=False, details=["AP disconnect"]),
        ]

        report = build_prediction_report(results)

        assert report.execution_safe is False
        assert report.critical == 2


# ---------------------------------------------------------------------------
# test_compute_overall_severity
# ---------------------------------------------------------------------------


class TestComputeOverallSeverity:
    def test_pass_only(self):
        assert compute_overall_severity([_result("A", "pass")]) == "clean"

    def test_skipped_only(self):
        assert compute_overall_severity([_result("A", "skipped")]) == "clean"

    def test_warning_is_worst(self):
        results = [_result("A", "pass"), _result("B", "warning")]
        assert compute_overall_severity(results) == "warning"

    def test_critical_is_worst(self):
        results = [_result("A", "pass"), _result("B", "warning"), _result("C", "critical")]
        assert compute_overall_severity(results) == "critical"

    def test_empty_list(self):
        assert compute_overall_severity([]) == "clean"

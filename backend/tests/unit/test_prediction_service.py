"""Unit tests for the prediction service."""

import pytest

from app.modules.digital_twin.models import CheckResult
from app.modules.digital_twin.services.prediction_service import (
    build_prediction_report,
    compute_overall_severity,
)


@pytest.mark.unit
class TestComputeOverallSeverity:
    def test_all_pass(self):
        results = [
            CheckResult(check_id="L1-01", check_name="test", layer=1, status="pass", summary="ok"),
        ]
        assert compute_overall_severity(results) == "clean"

    def test_warning_is_warning(self):
        results = [
            CheckResult(check_id="L1-01", check_name="test", layer=1, status="pass", summary="ok"),
            CheckResult(check_id="L1-02", check_name="test", layer=1, status="warning", summary="warn"),
        ]
        assert compute_overall_severity(results) == "warning"

    def test_error_trumps_warning(self):
        results = [
            CheckResult(check_id="L1-01", check_name="test", layer=1, status="warning", summary="warn"),
            CheckResult(check_id="L1-02", check_name="test", layer=1, status="error", summary="err"),
        ]
        assert compute_overall_severity(results) == "error"

    def test_critical_trumps_all(self):
        results = [
            CheckResult(check_id="L1-01", check_name="test", layer=1, status="error", summary="err"),
            CheckResult(check_id="L1-02", check_name="test", layer=1, status="critical", summary="crit"),
        ]
        assert compute_overall_severity(results) == "critical"

    def test_skipped_ignored(self):
        results = [
            CheckResult(check_id="L1-01", check_name="test", layer=1, status="skipped", summary="skip"),
        ]
        assert compute_overall_severity(results) == "clean"


class TestBuildPredictionReport:
    def test_report_counts(self):
        results = [
            CheckResult(check_id="L1-01", check_name="a", layer=1, status="pass", summary="ok"),
            CheckResult(check_id="L1-02", check_name="b", layer=1, status="warning", summary="w"),
            CheckResult(check_id="L1-03", check_name="c", layer=1, status="error", summary="e"),
            CheckResult(check_id="L1-04", check_name="d", layer=1, status="critical", summary="c"),
            CheckResult(check_id="L1-05", check_name="e", layer=1, status="skipped", summary="s"),
        ]
        report = build_prediction_report(results)
        assert report.total_checks == 4  # excludes skipped
        assert report.passed == 1
        assert report.warnings == 1
        assert report.errors == 1
        assert report.critical == 1
        assert report.skipped == 1
        assert report.execution_safe is False
        assert report.overall_severity == "critical"

    def test_clean_report(self):
        results = [
            CheckResult(check_id="L1-01", check_name="a", layer=1, status="pass", summary="ok"),
        ]
        report = build_prediction_report(results)
        assert report.execution_safe is True
        assert report.overall_severity == "clean"


@pytest.mark.unit
class TestRunLayer1ChecksIds:
    """Verify that all 14 L1 check functions produce the correct check_id."""

    def test_all_check_ids_present(self):
        from app.modules.digital_twin.services.config_checks import (
            check_client_capacity_impact,
            check_dhcp_scope_overlap,
            check_dhcp_server_misconfiguration,
            check_dns_ntp_consistency,
            check_duplicate_ssid,
            check_ip_subnet_overlap,
            check_port_profile_conflict,
            check_psk_rotation_impact,
            check_rf_template_impact,
            check_ssid_airtime_overhead,
            check_subnet_collision_within_site,
            check_template_override_crush,
            check_unresolved_template_variables,
            check_vlan_id_collision,
        )

        assert check_ip_subnet_overlap([], []).check_id == "L1-01"
        assert check_subnet_collision_within_site([]).check_id == "L1-02"
        assert check_vlan_id_collision([]).check_id == "L1-03"
        assert check_duplicate_ssid([]).check_id == "L1-04"
        assert check_port_profile_conflict([], []).check_id == "L1-05"
        assert check_template_override_crush({}, {}, "s").check_id == "L1-06"
        assert check_unresolved_template_variables({}, {}, "t", "s").check_id == "L1-07"
        assert check_dhcp_scope_overlap([]).check_id == "L1-08"
        assert check_dhcp_server_misconfiguration([]).check_id == "L1-09"
        assert check_dns_ntp_consistency([]).check_id == "L1-10"
        assert check_ssid_airtime_overhead([]).check_id == "L1-11"
        assert check_psk_rotation_impact({}, {}, 0, "s").check_id == "L1-12"
        assert check_rf_template_impact({}, {}, 0).check_id == "L1-13"
        assert check_client_capacity_impact({}, {}, 0, "s").check_id == "L1-14"

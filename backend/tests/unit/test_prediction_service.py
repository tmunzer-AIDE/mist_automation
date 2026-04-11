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
        assert report.total_checks == 5
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

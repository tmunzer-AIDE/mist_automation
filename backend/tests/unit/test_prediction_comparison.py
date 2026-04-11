"""Unit tests for prediction comparison logic."""

import pytest

from app.modules.digital_twin.services.prediction_comparison import compare_prediction_vs_reality


@pytest.mark.unit
class TestComparisonAccuracy:
    def test_correct_prediction(self):
        prediction = {"overall_severity": "warning", "errors": 0, "critical": 0, "warnings": 2}
        result = compare_prediction_vs_reality(prediction, {}, "warning")
        assert result["accuracy"] == "correct"

    def test_over_prediction(self):
        prediction = {"overall_severity": "critical", "errors": 1, "critical": 1, "warnings": 0}
        result = compare_prediction_vs_reality(prediction, {}, "none")
        assert result["accuracy"] == "over_predicted"
        assert "false positive" in result["details"][0]

    def test_under_prediction(self):
        prediction = {"overall_severity": "clean", "errors": 0, "critical": 0, "warnings": 0}
        result = compare_prediction_vs_reality(prediction, {}, "critical")
        assert result["accuracy"] == "under_predicted"
        assert "not caught" in result["details"][0]

    def test_no_prediction(self):
        result = compare_prediction_vs_reality(None, {}, "warning")
        assert result["accuracy"] == "unknown"

    def test_clean_matches_none(self):
        prediction = {"overall_severity": "clean", "errors": 0, "critical": 0, "warnings": 0}
        result = compare_prediction_vs_reality(prediction, {}, "none")
        assert result["accuracy"] == "correct"

    def test_ia_failures_not_predicted(self):
        prediction = {"overall_severity": "clean", "errors": 0, "critical": 0, "warnings": 0}
        ia_results = {"connectivity": {"status": "fail"}, "sle": {"status": "warn"}}
        result = compare_prediction_vs_reality(prediction, ia_results, "warning")
        assert any("issue(s) that Twin did not predict" in d for d in result["details"])

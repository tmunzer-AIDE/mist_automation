"""
Unit tests for filter evaluation engine.
"""

import pytest
from app.utils.filters import (
    FilterOperator,
    FilterLogic,
    FilterEvaluationError,
    get_nested_value,
    evaluate_single_filter,
    evaluate_filter_group,
    evaluate_filters,
)


class TestGetNestedValue:
    """Test nested value extraction."""

    def test_simple_field(self):
        data = {"name": "test"}
        assert get_nested_value(data, "name") == "test"

    def test_nested_field(self):
        data = {"event": {"device": {"name": "AP-01"}}}
        assert get_nested_value(data, "event.device.name") == "AP-01"

    def test_missing_field(self):
        data = {"name": "test"}
        assert get_nested_value(data, "missing") is None

    def test_missing_nested_field(self):
        data = {"event": {"type": "alarm"}}
        assert get_nested_value(data, "event.device.name") is None

    def test_empty_path(self):
        data = {"name": "test"}
        assert get_nested_value(data, "") is None

    def test_non_dict_intermediate(self):
        data = {"event": "string"}
        assert get_nested_value(data, "event.device.name") is None


class TestStringFilters:
    """Test string filter operations."""

    def test_equals_true(self):
        filter_config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm"
        }
        data = {"type": "alarm"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_equals_false(self):
        filter_config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm"
        }
        data = {"type": "audit"}
        assert evaluate_single_filter(filter_config, data) is False

    def test_contains_true(self):
        filter_config = {
            "field": "message",
            "operator": "contains",
            "value": "offline"
        }
        data = {"message": "Device went offline"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_contains_false(self):
        filter_config = {
            "field": "message",
            "operator": "contains",
            "value": "offline"
        }
        data = {"message": "Device online"}
        assert evaluate_single_filter(filter_config, data) is False

    def test_starts_with_true(self):
        filter_config = {
            "field": "name",
            "operator": "starts_with",
            "value": "AP-"
        }
        data = {"name": "AP-01"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_starts_with_false(self):
        filter_config = {
            "field": "name",
            "operator": "starts_with",
            "value": "AP-"
        }
        data = {"name": "SW-01"}
        assert evaluate_single_filter(filter_config, data) is False

    def test_ends_with_true(self):
        filter_config = {
            "field": "name",
            "operator": "ends_with",
            "value": "-01"
        }
        data = {"name": "AP-01"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_ends_with_false(self):
        filter_config = {
            "field": "name",
            "operator": "ends_with",
            "value": "-01"
        }
        data = {"name": "AP-02"}
        assert evaluate_single_filter(filter_config, data) is False

    def test_regex_match(self):
        filter_config = {
            "field": "name",
            "operator": "regex",
            "value": r"AP-\d+"
        }
        data = {"name": "AP-123"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_regex_no_match(self):
        filter_config = {
            "field": "name",
            "operator": "regex",
            "value": r"AP-\d+"
        }
        data = {"name": "SW-123"}
        assert evaluate_single_filter(filter_config, data) is False

    def test_regex_invalid_pattern(self):
        filter_config = {
            "field": "name",
            "operator": "regex",
            "value": r"[invalid("
        }
        data = {"name": "test"}
        with pytest.raises(FilterEvaluationError, match="Invalid regex pattern"):
            evaluate_single_filter(filter_config, data)


class TestNumericFilters:
    """Test numeric filter operations."""

    def test_equals_true(self):
        filter_config = {
            "field": "count",
            "operator": "equals",
            "value": 5
        }
        data = {"count": 5}
        assert evaluate_single_filter(filter_config, data) is True

    def test_equals_false(self):
        filter_config = {
            "field": "count",
            "operator": "equals",
            "value": 5
        }
        data = {"count": 10}
        assert evaluate_single_filter(filter_config, data) is False

    def test_greater_than_true(self):
        filter_config = {
            "field": "count",
            "operator": "greater_than",
            "value": 5
        }
        data = {"count": 10}
        assert evaluate_single_filter(filter_config, data) is True

    def test_greater_than_false(self):
        filter_config = {
            "field": "count",
            "operator": "greater_than",
            "value": 5
        }
        data = {"count": 3}
        assert evaluate_single_filter(filter_config, data) is False

    def test_less_than_true(self):
        filter_config = {
            "field": "count",
            "operator": "less_than",
            "value": 10
        }
        data = {"count": 5}
        assert evaluate_single_filter(filter_config, data) is True

    def test_less_than_false(self):
        filter_config = {
            "field": "count",
            "operator": "less_than",
            "value": 10
        }
        data = {"count": 15}
        assert evaluate_single_filter(filter_config, data) is False

    def test_between_true(self):
        filter_config = {
            "field": "count",
            "operator": "between",
            "value": [5, 10]
        }
        data = {"count": 7}
        assert evaluate_single_filter(filter_config, data) is True

    def test_between_false(self):
        filter_config = {
            "field": "count",
            "operator": "between",
            "value": [5, 10]
        }
        data = {"count": 15}
        assert evaluate_single_filter(filter_config, data) is False

    def test_between_invalid_value(self):
        filter_config = {
            "field": "count",
            "operator": "between",
            "value": [5]  # Only one value
        }
        data = {"count": 7}
        with pytest.raises(FilterEvaluationError, match="requires a list of two values"):
            evaluate_single_filter(filter_config, data)

    def test_numeric_string_conversion(self):
        filter_config = {
            "field": "count",
            "operator": "greater_than",
            "value": "5"
        }
        data = {"count": "10"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_numeric_invalid_value(self):
        filter_config = {
            "field": "count",
            "operator": "greater_than",
            "value": 5
        }
        data = {"count": "not_a_number"}
        assert evaluate_single_filter(filter_config, data) is False


class TestBooleanFilters:
    """Test boolean filter operations."""

    def test_is_true_with_bool(self):
        filter_config = {
            "field": "active",
            "operator": "is_true"
        }
        data = {"active": True}
        assert evaluate_single_filter(filter_config, data) is True

    def test_is_true_with_string(self):
        filter_config = {
            "field": "active",
            "operator": "is_true"
        }
        data = {"active": "true"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_is_true_with_number(self):
        filter_config = {
            "field": "active",
            "operator": "is_true"
        }
        data = {"active": 1}
        assert evaluate_single_filter(filter_config, data) is True

    def test_is_false_with_bool(self):
        filter_config = {
            "field": "active",
            "operator": "is_false"
        }
        data = {"active": False}
        assert evaluate_single_filter(filter_config, data) is True

    def test_is_false_with_string(self):
        filter_config = {
            "field": "active",
            "operator": "is_false"
        }
        data = {"active": "false"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_is_false_with_zero(self):
        filter_config = {
            "field": "active",
            "operator": "is_false"
        }
        data = {"active": 0}
        assert evaluate_single_filter(filter_config, data) is True


class TestListFilters:
    """Test list filter operations."""

    def test_in_list_true(self):
        filter_config = {
            "field": "severity",
            "operator": "in_list",
            "value": ["critical", "major", "minor"]
        }
        data = {"severity": "critical"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_in_list_false(self):
        filter_config = {
            "field": "severity",
            "operator": "in_list",
            "value": ["critical", "major"]
        }
        data = {"severity": "minor"}
        assert evaluate_single_filter(filter_config, data) is False

    def test_not_in_list_true(self):
        filter_config = {
            "field": "severity",
            "operator": "not_in_list",
            "value": ["info", "debug"]
        }
        data = {"severity": "critical"}
        assert evaluate_single_filter(filter_config, data) is True

    def test_not_in_list_false(self):
        filter_config = {
            "field": "severity",
            "operator": "not_in_list",
            "value": ["critical", "major"]
        }
        data = {"severity": "critical"}
        assert evaluate_single_filter(filter_config, data) is False

    def test_in_list_invalid_value(self):
        filter_config = {
            "field": "severity",
            "operator": "in_list",
            "value": "not_a_list"
        }
        data = {"severity": "critical"}
        with pytest.raises(FilterEvaluationError, match="List operators require a list value"):
            evaluate_single_filter(filter_config, data)


class TestFilterValidation:
    """Test filter configuration validation."""

    def test_missing_field(self):
        filter_config = {
            "operator": "equals",
            "value": "test"
        }
        data = {"name": "test"}
        with pytest.raises(FilterEvaluationError, match="missing required field: field"):
            evaluate_single_filter(filter_config, data)

    def test_missing_operator(self):
        filter_config = {
            "field": "name",
            "value": "test"
        }
        data = {"name": "test"}
        with pytest.raises(FilterEvaluationError, match="missing required field: operator"):
            evaluate_single_filter(filter_config, data)

    def test_invalid_operator(self):
        filter_config = {
            "field": "name",
            "operator": "invalid_op",
            "value": "test"
        }
        data = {"name": "test"}
        with pytest.raises(FilterEvaluationError, match="Invalid operator"):
            evaluate_single_filter(filter_config, data)

    def test_not_a_dict(self):
        filter_config = "not a dict"
        data = {"name": "test"}
        with pytest.raises(FilterEvaluationError, match="must be a dictionary"):
            evaluate_single_filter(filter_config, data)


class TestFilterGroups:
    """Test filter group evaluation."""

    def test_empty_filter_list(self):
        filters = []
        data = {"name": "test"}
        assert evaluate_filter_group(filters, data) is True

    def test_and_logic_all_pass(self):
        filters = [
            {"field": "type", "operator": "equals", "value": "alarm"},
            {"field": "severity", "operator": "equals", "value": "critical"}
        ]
        data = {"type": "alarm", "severity": "critical"}
        assert evaluate_filter_group(filters, data, FilterLogic.AND) is True

    def test_and_logic_one_fails(self):
        filters = [
            {"field": "type", "operator": "equals", "value": "alarm"},
            {"field": "severity", "operator": "equals", "value": "critical"}
        ]
        data = {"type": "alarm", "severity": "major"}
        assert evaluate_filter_group(filters, data, FilterLogic.AND) is False

    def test_or_logic_one_passes(self):
        filters = [
            {"field": "type", "operator": "equals", "value": "alarm"},
            {"field": "type", "operator": "equals", "value": "audit"}
        ]
        data = {"type": "alarm"}
        assert evaluate_filter_group(filters, data, FilterLogic.OR) is True

    def test_or_logic_all_fail(self):
        filters = [
            {"field": "type", "operator": "equals", "value": "alarm"},
            {"field": "type", "operator": "equals", "value": "audit"}
        ]
        data = {"type": "event"}
        assert evaluate_filter_group(filters, data, FilterLogic.OR) is False

    def test_nested_group_with_logic(self):
        filter_group = {
            "logic": "or",
            "filters": [
                {"field": "type", "operator": "equals", "value": "alarm"},
                {"field": "type", "operator": "equals", "value": "audit"}
            ]
        }
        data = {"type": "alarm"}
        assert evaluate_filter_group(filter_group, data) is True


class TestEvaluateFilters:
    """Test complete filter evaluation with detailed results."""

    def test_empty_filters(self):
        result = evaluate_filters([], {"name": "test"})
        assert result["passed"] is True
        assert result["filter_results"] == []

    def test_all_filters_pass(self):
        filters = [
            {"field": "type", "operator": "equals", "value": "alarm"},
            {"field": "severity", "operator": "in_list", "value": ["critical", "major"]}
        ]
        data = {"type": "alarm", "severity": "critical"}
        result = evaluate_filters(filters, data)

        assert result["passed"] is True
        assert len(result["filter_results"]) == 2
        assert all(r["passed"] for r in result["filter_results"])

    def test_one_filter_fails(self):
        filters = [
            {"field": "type", "operator": "equals", "value": "alarm"},
            {"field": "severity", "operator": "equals", "value": "critical"}
        ]
        data = {"type": "alarm", "severity": "major"}
        result = evaluate_filters(filters, data)

        assert result["passed"] is False
        assert len(result["filter_results"]) == 2
        assert result["filter_results"][0]["passed"] is True
        assert result["filter_results"][1]["passed"] is False

    def test_detailed_results(self):
        filters = [
            {"field": "type", "operator": "equals", "value": "alarm"}
        ]
        data = {"type": "alarm"}
        result = evaluate_filters(filters, data)

        assert "filter_results" in result
        assert result["filter_results"][0]["filter_type"] == "single"
        assert result["filter_results"][0]["field"] == "type"
        assert result["filter_results"][0]["operator"] == "equals"
        assert result["filter_results"][0]["expected_value"] == "alarm"
        assert result["filter_results"][0]["actual_value"] == "alarm"

    def test_filter_error_handling(self):
        filters = [
            {"field": "name", "operator": "invalid", "value": "test"}
        ]
        data = {"name": "test"}
        result = evaluate_filters(filters, data)

        assert result["passed"] is False
        assert "error" in result["filter_results"][0]

    def test_nested_field_extraction(self):
        filters = [
            {"field": "event.device.name", "operator": "equals", "value": "AP-01"}
        ]
        data = {"event": {"device": {"name": "AP-01"}}}
        result = evaluate_filters(filters, data)

        assert result["passed"] is True
        assert result["filter_results"][0]["actual_value"] == "AP-01"


class TestSourceFiltering:
    """Test source-based filter evaluation."""

    def test_webhook_source_matches(self):
        filter_config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm",
            "source": "webhook"
        }
        data = {"type": "alarm"}
        assert evaluate_single_filter(filter_config, data, source="webhook") is True

    def test_source_mismatch_skips(self):
        filter_config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm",
            "source": "api_result"
        }
        data = {"type": "event"}  # Would fail if evaluated
        # Should skip this filter and return True
        assert evaluate_single_filter(filter_config, data, source="webhook") is True

    def test_default_source_is_webhook(self):
        filter_config = {
            "field": "type",
            "operator": "equals",
            "value": "alarm"
        }
        data = {"type": "alarm"}
        assert evaluate_single_filter(filter_config, data) is True

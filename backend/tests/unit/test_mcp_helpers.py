"""
Unit tests for MCP server helper utilities.
"""

import json
from datetime import datetime, timezone

import pytest

from app.modules.mcp_server.helpers import (
    cap_list,
    compact_results,
    extract_fields,
    get_nested_value,
    prune_config,
    to_json,
    truncate_value,
)


@pytest.mark.unit
class TestTruncateValue:
    """Test truncate_value function."""

    def test_string_under_limit_unchanged(self):
        result = truncate_value("short string", max_len=500)
        assert result == "short string"

    def test_string_at_limit_unchanged(self):
        value = "a" * 500
        result = truncate_value(value, max_len=500)
        assert result == value
        assert len(result) == 500

    def test_string_over_limit_truncated(self):
        value = "a" * 501
        result = truncate_value(value, max_len=500)
        assert result == "a" * 500 + "..."
        assert len(result) == 503

    def test_int_unchanged(self):
        assert truncate_value(42) == 42

    def test_dict_unchanged(self):
        d = {"key": "value"}
        assert truncate_value(d) == d

    def test_list_unchanged(self):
        lst = [1, 2, 3]
        assert truncate_value(lst) == lst


@pytest.mark.unit
class TestPruneConfig:
    """Test prune_config function."""

    def test_dict_with_few_keys_truncates_strings(self):
        config = {"name": "short", "description": "x" * 600}
        result = prune_config(config, max_keys=30, max_value_len=500)
        assert result["name"] == "short"
        assert result["description"] == "x" * 500 + "..."

    def test_nested_dict_shows_summary(self):
        config = {"nested": {"a": 1, "b": 2, "c": 3}}
        result = prune_config(config)
        assert result["nested"] == "{...} (3 keys)"

    def test_nested_list_shows_summary(self):
        config = {"items": [1, 2, 3, 4, 5]}
        result = prune_config(config)
        assert result["items"] == "[...] (5 items)"

    def test_exceeding_max_keys_adds_truncated_marker(self):
        config = {f"key_{i}": i for i in range(10)}
        result = prune_config(config, max_keys=3)
        assert len(result) == 4  # 3 keys + __truncated__
        assert "__truncated__" in result
        assert result["__truncated__"] == "7 more keys"

    def test_non_dict_returns_as_is(self):
        assert prune_config("not a dict") == "not a dict"
        assert prune_config(42) == 42
        assert prune_config([1, 2]) == [1, 2]

    def test_empty_dict_returns_empty(self):
        assert prune_config({}) == {}


@pytest.mark.unit
class TestCompactResults:
    """Test compact_results function."""

    def test_extracts_specified_fields(self):
        items = [
            {"id": "1", "name": "Alice", "email": "alice@example.com", "extra": "data"},
            {"id": "2", "name": "Bob", "email": "bob@example.com", "extra": "more"},
        ]
        result = compact_results(items, ["id", "name"])
        assert result == [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]

    def test_missing_fields_skipped(self):
        items = [{"id": "1", "name": "Alice"}, {"id": "2"}]
        result = compact_results(items, ["id", "name", "missing"])
        assert result == [{"id": "1", "name": "Alice"}, {"id": "2"}]
        # Verify missing field is not set to None
        assert "missing" not in result[0]
        assert "name" not in result[1]

    def test_empty_items_returns_empty(self):
        assert compact_results([], ["id", "name"]) == []


@pytest.mark.unit
class TestCapList:
    """Test cap_list function."""

    def test_under_limit_returns_same(self):
        items = [1, 2, 3]
        result = cap_list(items, limit=50)
        assert result == [1, 2, 3]

    def test_at_limit_returns_same(self):
        items = list(range(50))
        result = cap_list(items, limit=50)
        assert result == items

    def test_over_limit_truncates_with_note(self):
        items = list(range(60))
        result = cap_list(items, limit=50)
        assert len(result) == 51  # 50 items + 1 note
        assert result[:50] == list(range(50))
        assert result[50] == {"__note__": "10 more items not shown"}


@pytest.mark.unit
class TestToJson:
    """Test to_json function."""

    def test_datetime_serialized_to_iso(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = to_json({"timestamp": dt})
        parsed = json.loads(result)
        assert parsed["timestamp"] == "2024-01-15T10:30:00+00:00"

    def test_non_serializable_uses_str(self):
        class Custom:
            def __str__(self):
                return "custom_repr"

        result = to_json({"obj": Custom()})
        parsed = json.loads(result)
        assert parsed["obj"] == "custom_repr"

    def test_returns_compact_json_string(self):
        result = to_json({"key": "value", "num": 42})
        assert isinstance(result, str)
        # Compact means no extra spaces after : and ,
        parsed = json.loads(result)
        assert parsed == {"key": "value", "num": 42}


@pytest.mark.unit
class TestGetNestedValue:
    """Test get_nested_value function."""

    def test_simple_key_access(self):
        data = {"name": "Alice"}
        assert get_nested_value(data, "name") == "Alice"

    def test_dot_notation_nested_access(self):
        data = {"user": {"profile": {"name": "Alice"}}}
        assert get_nested_value(data, "user.profile.name") == "Alice"

    def test_missing_key_returns_none(self):
        data = {"name": "Alice"}
        assert get_nested_value(data, "missing") is None

    def test_non_dict_intermediate_returns_none(self):
        data = {"user": "not_a_dict"}
        assert get_nested_value(data, "user.name") is None


@pytest.mark.unit
class TestExtractFields:
    """Test extract_fields function."""

    def test_extracts_dot_notation_fields(self):
        config = {"network": {"ip": "10.0.0.1"}, "name": "gw1"}
        result = extract_fields(config, ["name", "network.ip"])
        assert result == {"name": "gw1", "network.ip": "10.0.0.1"}

    def test_missing_fields_skipped(self):
        config = {"name": "gw1"}
        result = extract_fields(config, ["name", "missing_field"])
        assert result == {"name": "gw1"}
        assert "missing_field" not in result

    def test_values_truncated(self):
        config = {"description": "x" * 600}
        result = extract_fields(config, ["description"])
        assert result["description"] == "x" * 500 + "..."

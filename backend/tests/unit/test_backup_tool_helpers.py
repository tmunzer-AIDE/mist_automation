"""Unit tests for pure helpers in the MCP backup tool.

Focused on event-type classification and the handlers' structural behavior. Full
database-backed tests for _object_info / _version_detail live in integration tests.
"""

from enum import Enum

import pytest

from app.modules.mcp_server.helpers import prune_config
from app.modules.mcp_server.tools.backup import (
    _DATA_EVENT_TYPES,
    _event_type_str,
    _is_data_event,
)


class _FakeEventType(str, Enum):
    """Mirror of BackupEventType for tests that don't need the full model."""

    FULL_BACKUP = "full_backup"
    UPDATED = "updated"
    CREATED = "created"
    RESTORED = "restored"
    DELETED = "deleted"
    INCREMENTAL = "incremental"


@pytest.mark.unit
class TestEventTypeClassification:
    def test_data_event_types_cover_live_captures(self):
        # These four carry the current live configuration in the backup snapshot.
        assert "full_backup" in _DATA_EVENT_TYPES
        assert "updated" in _DATA_EVENT_TYPES
        assert "created" in _DATA_EVENT_TYPES
        assert "incremental" in _DATA_EVENT_TYPES

    def test_restored_is_not_a_data_event(self):
        # 'restored' and 'deleted' should NOT be treated as authoritative live config.
        assert "restored" not in _DATA_EVENT_TYPES
        assert "deleted" not in _DATA_EVENT_TYPES

    def test_event_type_str_handles_enum_and_string(self):
        assert _event_type_str(_FakeEventType.UPDATED) == "updated"
        assert _event_type_str(_FakeEventType.RESTORED) == "restored"
        assert _event_type_str("full_backup") == "full_backup"

    def test_is_data_event_accepts_enum(self):
        assert _is_data_event(_FakeEventType.UPDATED) is True
        assert _is_data_event(_FakeEventType.FULL_BACKUP) is True
        assert _is_data_event(_FakeEventType.CREATED) is True
        assert _is_data_event(_FakeEventType.RESTORED) is False
        assert _is_data_event(_FakeEventType.DELETED) is False

    def test_is_data_event_accepts_string(self):
        assert _is_data_event("updated") is True
        assert _is_data_event("restored") is False
        assert _is_data_event("unknown_event") is False


@pytest.mark.unit
class TestPruneConfigBehavior:
    """Tests for helpers.prune_config — inline_keys and small-dict auto-expand."""

    def test_inline_keys_expands_nested_dicts_fully(self):
        cfg = {
            "name": "switch-01",
            "port_config": {
                "ge-0/0/8": {
                    "usage": "disabled",
                    "description": "",
                    "critical": False,
                },
            },
        }

        result = prune_config(cfg, inline_keys={"port_config"})

        assert result["port_config"]["ge-0/0/8"]["usage"] == "disabled"
        assert result["port_config"]["ge-0/0/8"]["critical"] is False

    def test_small_dict_auto_expand_without_inline_keys(self):
        # A nested dict with a single key should render inline even when the caller
        # did not pass inline_keys — that's the whole point of small-dict auto-expand.
        cfg = {
            "port_config": {
                "ge-0/0/8": {"usage": "disabled"},
            },
        }

        result = prune_config(cfg)

        assert isinstance(result["port_config"], dict)
        assert "ge-0/0/8" in result["port_config"]

    def test_large_dict_still_summarized(self):
        # 20 keys is above small_dict_threshold (default 3) — should summarize.
        large_nested = {f"key_{i}": {"sub": i} for i in range(20)}
        cfg = {"bulk": large_nested}

        result = prune_config(cfg)

        assert isinstance(result["bulk"], str)
        assert "20 keys" in result["bulk"]

    def test_inline_keys_overrides_summary_for_large_dicts(self):
        large_nested = {f"port_{i}": {"usage": "enabled"} for i in range(20)}
        cfg = {"port_config": large_nested}

        result = prune_config(cfg, inline_keys={"port_config"})

        assert isinstance(result["port_config"], dict)
        assert len(result["port_config"]) == 20
        assert result["port_config"]["port_0"]["usage"] == "enabled"

    def test_inline_keys_still_truncates_long_strings(self):
        cfg = {"notes": {"detail": "x" * 2000}}

        result = prune_config(cfg, inline_keys={"notes"}, max_value_len=100)

        assert isinstance(result["notes"]["detail"], str)
        assert result["notes"]["detail"].endswith("...")
        assert len(result["notes"]["detail"]) <= 103  # 100 + "..."

    def test_inline_keys_apply_cardinality_caps(self):
        cfg = {
            "port_config": {
                f"port_{i}": {"usage": "enabled"}
                for i in range(250)
            }
        }

        result = prune_config(cfg, inline_keys={"port_config"})

        assert isinstance(result["port_config"], dict)
        assert result["port_config"]["port_0"]["usage"] == "enabled"
        assert "__truncated__" in result["port_config"]
        assert "50 more keys" in result["port_config"]["__truncated__"]

    def test_default_call_matches_old_behavior_for_flat_scalars(self):
        # Existing callers that pass a flat dict of scalars should see the same output
        # they used to get — regression guard.
        cfg = {"name": "switch-01", "role": "access", "version": 42}

        result = prune_config(cfg)

        assert result == {"name": "switch-01", "role": "access", "version": 42}

    def test_top_level_max_keys_still_enforced(self):
        cfg = {f"field_{i}": i for i in range(35)}

        result = prune_config(cfg, max_keys=30)

        assert "__truncated__" in result
        assert "5 more keys" in result["__truncated__"]

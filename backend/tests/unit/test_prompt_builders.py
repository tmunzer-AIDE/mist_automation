"""
Unit tests for LLM prompt builder functions.

All functions under test are pure (no I/O), so no mocking is needed.
"""

import pytest

from app.modules.llm.services.prompt_builders import (
    _sanitize_for_prompt,
    build_backup_summary_prompt,
    build_debug_prompt,
    build_field_assist_prompt,
    build_global_chat_system_prompt,
    build_webhook_summary_prompt,
)

pytestmark = pytest.mark.unit


# ── _sanitize_for_prompt ─────────────────────────────────────────────────────


class TestSanitizeForPrompt:
    """Tests for _sanitize_for_prompt(value, max_len=200)."""

    def test_truncates_long_string(self):
        long_value = "a" * 300
        result = _sanitize_for_prompt(long_value)
        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")

    def test_truncates_at_custom_max_len(self):
        value = "a" * 100
        result = _sanitize_for_prompt(value, max_len=50)
        assert len(result) == 53  # 50 + "..."
        assert result.endswith("...")

    def test_no_truncation_within_limit(self):
        value = "short string"
        result = _sanitize_for_prompt(value)
        assert result == "short string"

    def test_strips_triple_backticks(self):
        value = "before```after"
        result = _sanitize_for_prompt(value)
        assert "```" not in result
        assert result == "beforeafter"

    def test_strips_triple_dashes(self):
        value = "before---after"
        result = _sanitize_for_prompt(value)
        assert "---" not in result
        assert result == "beforeafter"

    def test_strips_triple_asterisks(self):
        value = "before***after"
        result = _sanitize_for_prompt(value)
        assert "***" not in result
        assert result == "beforeafter"

    def test_strips_all_dangerous_sequences(self):
        value = "a```b---c***d"
        result = _sanitize_for_prompt(value)
        assert result == "abcd"

    def test_empty_string_returns_empty_string(self):
        result = _sanitize_for_prompt("")
        assert result == ""

    def test_none_returns_none(self):
        # The function checks `if not value: return value` — None is falsy
        result = _sanitize_for_prompt(None)
        assert result is None

    def test_exact_max_len_no_truncation(self):
        value = "a" * 200
        result = _sanitize_for_prompt(value)
        assert result == value
        assert len(result) == 200

    def test_one_over_max_len_truncates(self):
        value = "a" * 201
        result = _sanitize_for_prompt(value)
        assert len(result) == 203  # 200 + "..."

    def test_stripping_reduces_length_below_max(self):
        """After stripping, the string may be shorter than max_len."""
        value = "x" * 50 + "```" + "y" * 50
        result = _sanitize_for_prompt(value, max_len=200)
        assert "```" not in result
        assert len(result) == 100


# ── build_backup_summary_prompt ──────────────────────────────────────────────


class TestBuildBackupSummaryPrompt:
    """Tests for build_backup_summary_prompt."""

    def _make_prompt(self, **kwargs):
        defaults = {
            "diff_entries": [{"field": "name", "old": "a", "new": "b"}],
            "object_type": "wlan",
            "object_name": "TestWLAN",
            "old_version": 1,
            "new_version": 2,
            "event_type": "updated",
            "changed_fields": ["name", "ssid"],
        }
        defaults.update(kwargs)
        return build_backup_summary_prompt(**defaults)

    def test_returns_two_messages(self):
        result = self._make_prompt()
        assert len(result) == 2

    def test_first_message_is_system(self):
        result = self._make_prompt()
        assert result[0]["role"] == "system"

    def test_second_message_is_user(self):
        result = self._make_prompt()
        assert result[1]["role"] == "user"

    def test_object_name_backticks_stripped(self):
        result = self._make_prompt(object_name="My```WLAN")
        user_content = result[1]["content"]
        assert "```" not in user_content.split("**Detailed diff**")[0]
        assert "MyWLAN" in user_content

    def test_object_type_sanitized(self):
        result = self._make_prompt(object_type="wlan```injected")
        user_content = result[1]["content"]
        assert "wlaninjected" in user_content

    def test_changed_fields_sanitized(self):
        result = self._make_prompt(changed_fields=["field```one", "field---two"])
        user_content = result[1]["content"]
        assert "fieldone" in user_content
        assert "fieldtwo" in user_content

    def test_diff_truncated_to_100_entries(self):
        many_entries = [{"field": f"f{i}", "old": "a", "new": "b"} for i in range(150)]
        result = self._make_prompt(diff_entries=many_entries)
        user_content = result[1]["content"]
        assert "50 more changes" in user_content

    def test_diff_not_truncated_under_100(self):
        entries = [{"field": f"f{i}"} for i in range(50)]
        result = self._make_prompt(diff_entries=entries)
        user_content = result[1]["content"]
        assert "more changes" not in user_content

    def test_context_lines_when_object_id_provided(self):
        result = self._make_prompt(
            object_id="abc-123",
            version_id_1="v1-id",
            version_id_2="v2-id",
        )
        system_content = result[0]["content"]
        assert "Object ID (Mist UUID): abc-123" in system_content
        assert "v1-id" in system_content
        assert "v2-id" in system_content

    def test_no_context_lines_without_object_id(self):
        result = self._make_prompt()
        system_content = result[0]["content"]
        assert "Object ID" not in system_content

    def test_unnamed_object_fallback(self):
        result = self._make_prompt(object_name=None)
        user_content = result[1]["content"]
        assert "(unnamed)" in user_content

    def test_empty_changed_fields(self):
        result = self._make_prompt(changed_fields=[])
        user_content = result[1]["content"]
        assert "N/A" in user_content


# ── build_global_chat_system_prompt ──────────────────────────────────────────


class TestBuildGlobalChatSystemPrompt:
    """Tests for build_global_chat_system_prompt."""

    def test_known_roles_included(self):
        result = build_global_chat_system_prompt(["admin", "automation"])
        assert "admin" in result
        assert "automation" in result

    def test_all_known_roles(self):
        result = build_global_chat_system_prompt(["admin", "automation", "backup", "post_deployment", "impact_analysis"])
        for role in ["admin", "automation", "backup", "post_deployment", "impact_analysis"]:
            assert role in result

    def test_unknown_roles_filtered_out(self):
        result = build_global_chat_system_prompt(["admin", "hacker", "superuser"])
        assert "hacker" not in result
        assert "superuser" not in result
        assert "admin" in result

    def test_all_unknown_roles_returns_none(self):
        result = build_global_chat_system_prompt(["hacker", "superuser"])
        assert "roles: none" in result

    def test_empty_list_returns_none(self):
        result = build_global_chat_system_prompt([])
        assert "roles: none" in result

    def test_none_input_returns_none(self):
        result = build_global_chat_system_prompt(None)
        assert "roles: none" in result

    def test_returns_string(self):
        result = build_global_chat_system_prompt(["admin"])
        assert isinstance(result, str)


# ── build_field_assist_prompt ────────────────────────────────────────────────


class TestBuildFieldAssistPrompt:
    """Tests for build_field_assist_prompt."""

    def test_returns_two_messages(self):
        result = build_field_assist_prompt("mist_api_get", "api_endpoint", "The API path")
        assert len(result) == 2

    def test_system_role(self):
        result = build_field_assist_prompt("mist_api_get", "api_endpoint", "The API path")
        assert result[0]["role"] == "system"

    def test_user_role(self):
        result = build_field_assist_prompt("mist_api_get", "api_endpoint", "The API path")
        assert result[1]["role"] == "user"

    def test_node_type_sanitized(self):
        result = build_field_assist_prompt("mist```api", "field", "desc")
        user_content = result[1]["content"]
        assert "```" not in user_content
        assert "mistapi" in user_content

    def test_field_name_sanitized(self):
        result = build_field_assist_prompt("type", "field---name", "desc")
        user_content = result[1]["content"]
        assert "---" not in user_content
        assert "fieldname" in user_content

    def test_description_sanitized_with_max_2000(self):
        long_desc = "x" * 2500
        result = build_field_assist_prompt("type", "field", long_desc)
        user_content = result[1]["content"]
        # The description portion should be truncated at 2000 + "..."
        assert "..." in user_content

    def test_upstream_variables_included(self):
        variables = {"trigger": {"type": "ap_online", "site_id": "abc"}}
        result = build_field_assist_prompt("type", "field", "desc", upstream_variables=variables)
        user_content = result[1]["content"]
        assert "upstream variables" in user_content.lower()
        assert "ap_online" in user_content

    def test_no_upstream_variables(self):
        result = build_field_assist_prompt("type", "field", "desc", upstream_variables=None)
        user_content = result[1]["content"]
        assert "upstream variables" not in user_content.lower()

    def test_empty_upstream_variables_dict(self):
        """An empty dict is falsy, so no variables section should appear."""
        result = build_field_assist_prompt("type", "field", "desc", upstream_variables={})
        user_content = result[1]["content"]
        assert "upstream variables" not in user_content.lower()

    def test_node_type_max_len_50(self):
        long_type = "a" * 100
        result = build_field_assist_prompt(long_type, "field", "desc")
        user_content = result[1]["content"]
        # The sanitized node type should be truncated (50 + "...")
        assert "a" * 50 + "..." in user_content

    def test_field_name_max_len_100(self):
        long_field = "b" * 200
        result = build_field_assist_prompt("type", long_field, "desc")
        user_content = result[1]["content"]
        assert "b" * 100 + "..." in user_content


# ── build_debug_prompt ───────────────────────────────────────────────────────


class TestBuildDebugPrompt:
    """Tests for build_debug_prompt."""

    def test_returns_two_messages(self):
        result = build_debug_prompt({"status": "failed"}, [], [])
        assert len(result) == 2

    def test_system_role(self):
        result = build_debug_prompt({"status": "failed"}, [], [])
        assert result[0]["role"] == "system"

    def test_user_role(self):
        result = build_debug_prompt({"status": "failed"}, [], [])
        assert result[1]["role"] == "user"

    def test_nodes_truncated_to_10(self):
        many_nodes = [{"id": f"n{i}", "error": "fail"} for i in range(20)]
        result = build_debug_prompt({"status": "failed"}, many_nodes, [])
        user_content = result[1]["content"]
        # Only first 10 nodes should be in the JSON
        assert '"n9"' in user_content
        assert '"n10"' not in user_content

    def test_logs_truncated_to_last_30(self):
        many_logs = [f"log line {i}" for i in range(50)]
        result = build_debug_prompt({"status": "failed"}, [], many_logs)
        user_content = result[1]["content"]
        # First 20 lines should be dropped, line 20 onward kept
        assert "log line 20" in user_content
        assert "log line 49" in user_content
        assert "log line 19" not in user_content

    def test_empty_logs_shows_no_logs(self):
        result = build_debug_prompt({"status": "failed"}, [], [])
        user_content = result[1]["content"]
        assert "(no logs)" in user_content

    def test_execution_summary_fields_in_output(self):
        summary = {
            "status": "failed",
            "duration_ms": 1234,
            "nodes_succeeded": 3,
            "nodes_failed": 1,
        }
        result = build_debug_prompt(summary, [], [])
        user_content = result[1]["content"]
        assert "failed" in user_content
        assert "1234" in user_content
        assert "3 succeeded" in user_content
        assert "1 failed" in user_content


# ── build_webhook_summary_prompt ─────────────────────────────────────────────


class TestBuildWebhookSummaryPrompt:
    """Tests for build_webhook_summary_prompt."""

    def test_returns_two_messages(self):
        result = build_webhook_summary_prompt("some events", 24)
        assert len(result) == 2

    def test_system_role(self):
        result = build_webhook_summary_prompt("some events", 24)
        assert result[0]["role"] == "system"

    def test_user_role(self):
        result = build_webhook_summary_prompt("some events", 24)
        assert result[1]["role"] == "user"

    def test_time_range_in_user_message(self):
        result = build_webhook_summary_prompt("events", 12)
        user_content = result[1]["content"]
        assert "12 hours" in user_content

    def test_events_summary_in_user_message(self):
        result = build_webhook_summary_prompt("AP-01 went offline 5 times", 24)
        user_content = result[1]["content"]
        assert "AP-01 went offline 5 times" in user_content

    def test_system_mentions_network_operations(self):
        result = build_webhook_summary_prompt("events", 1)
        system_content = result[0]["content"]
        assert "network" in system_content.lower() or "Mist" in system_content

"""Unit tests for the Slack-rendering helpers on WorkflowExecutor.

These cover the pure helpers that don't require Beanie/Mongo:
- ``_extract_slack_blocks`` (static)
- ``_derive_slack_fallback_text`` (static)
"""

from app.modules.automation.services.executor_service import WorkflowExecutor


class TestExtractSlackBlocks:
    def test_dict_with_blocks_key(self):
        data = {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]}
        assert WorkflowExecutor._extract_slack_blocks(data) == data["blocks"]

    def test_bare_list_of_block_dicts(self):
        # A variable resolved to a raw Block Kit list (e.g., from format_report
        # with format=slack) must be recognized as Block Kit, not wrapped in a
        # JSON code block.
        data = [
            {"type": "header", "text": {"type": "plain_text", "text": "Title"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "body"}},
        ]
        assert WorkflowExecutor._extract_slack_blocks(data) == data

    def test_empty_list_returns_none(self):
        assert WorkflowExecutor._extract_slack_blocks([]) is None

    def test_list_with_non_block_element_returns_none(self):
        # If even one element lacks a ``type`` key, treat as generic data
        bad = [{"type": "section"}, {"foo": "bar"}]
        assert WorkflowExecutor._extract_slack_blocks(bad) is None

    def test_list_of_strings_returns_none(self):
        assert WorkflowExecutor._extract_slack_blocks(["a", "b"]) is None

    def test_string_with_embedded_blocks_json(self):
        data = '```json\n{"blocks": [{"type": "section"}]}\n```'
        result = WorkflowExecutor._extract_slack_blocks(data)
        assert result == [{"type": "section"}]

    def test_arbitrary_dict_without_blocks_key(self):
        assert WorkflowExecutor._extract_slack_blocks({"foo": "bar"}) is None


class TestDeriveSlackFallbackText:
    def test_section_with_mrkdwn(self):
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "*Alert:* device down"}}]
        assert WorkflowExecutor._derive_slack_fallback_text(blocks) == "*Alert:* device down"

    def test_first_block_wins(self):
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Header"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Body"}},
        ]
        assert WorkflowExecutor._derive_slack_fallback_text(blocks) == "Header"

    def test_truncates_to_150_chars(self):
        long = "x" * 500
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": long}}]
        result = WorkflowExecutor._derive_slack_fallback_text(blocks)
        assert len(result) == 150

    def test_context_block_with_elements(self):
        blocks = [
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "Footer text"}],
            }
        ]
        assert WorkflowExecutor._derive_slack_fallback_text(blocks) == "Footer text"

    def test_empty_blocks_returns_empty_string(self):
        assert WorkflowExecutor._derive_slack_fallback_text([]) == ""
        assert WorkflowExecutor._derive_slack_fallback_text(None) == ""

    def test_block_without_text_skipped(self):
        blocks = [
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Real text"}},
        ]
        assert WorkflowExecutor._derive_slack_fallback_text(blocks) == "Real text"

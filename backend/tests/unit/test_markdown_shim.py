"""Unit tests for the Markdown→Slack mrkdwn compatibility shim."""

from app.modules.automation.services.executor_service import convert_markdown_to_mrkdwn


class TestMarkdownShimGuaranteedConversions:
    def test_double_asterisk_bold(self):
        assert convert_markdown_to_mrkdwn("**bold**") == "*bold*"

    def test_double_underscore_bold(self):
        assert convert_markdown_to_mrkdwn("__bold__") == "*bold*"

    def test_strikethrough(self):
        assert convert_markdown_to_mrkdwn("~~strikethrough~~") == "~strikethrough~"

    def test_link_simple(self):
        assert convert_markdown_to_mrkdwn("[link](https://example.com)") == "<https://example.com|link>"

    def test_mixed_markdown(self):
        assert convert_markdown_to_mrkdwn("**bold** and ~~strike~~") == "*bold* and ~strike~"


class TestMarkdownShimIdempotency:
    def test_already_mrkdwn_bold(self):
        result = convert_markdown_to_mrkdwn("*bold*")
        assert result == "*bold*"
        assert convert_markdown_to_mrkdwn(result) == "*bold*"

    def test_already_mrkdwn_underscore_italic(self):
        result = convert_markdown_to_mrkdwn("_italic_")
        assert result == "_italic_"
        assert convert_markdown_to_mrkdwn(result) == "_italic_"

    def test_already_mrkdwn_tilde_strike(self):
        result = convert_markdown_to_mrkdwn("~strike~")
        assert result == "~strike~"
        assert convert_markdown_to_mrkdwn(result) == "~strike~"

    def test_already_mrkdwn_link(self):
        result = convert_markdown_to_mrkdwn("<https://x|y>")
        assert result == "<https://x|y>"
        assert convert_markdown_to_mrkdwn(result) == "<https://x|y>"


class TestMarkdownShimLinkSafety:
    def test_parentheses_in_url(self):
        # v1 does not implement balanced-parentheses URL parsing
        assert (
            convert_markdown_to_mrkdwn("[text](http://example.com/path(foo))") == "[text](http://example.com/path(foo))"
        )

    def test_lt_in_url(self):
        assert (
            convert_markdown_to_mrkdwn("[text](http://example.com/<unsafe>)") == "[text](http://example.com/<unsafe>)"
        )

    def test_gt_in_url(self):
        assert convert_markdown_to_mrkdwn("[text](http://example.com/>unsafe)") == "[text](http://example.com/>unsafe)"

    def test_whitespace_in_url(self):
        assert (
            convert_markdown_to_mrkdwn("[text](http://example.com/path with spaces)")
            == "[text](http://example.com/path with spaces)"
        )

    def test_pipe_in_display_text(self):
        assert convert_markdown_to_mrkdwn("[a|b](https://example.com)") == "[a|b](https://example.com)"

    def test_gt_in_display_text(self):
        assert convert_markdown_to_mrkdwn("[a>b](https://example.com)") == "[a>b](https://example.com)"


class TestMarkdownShimCodeProtection:
    def test_inline_code_span(self):
        assert convert_markdown_to_mrkdwn("`**not bold**`") == "`**not bold**`"

    def test_fenced_code_block(self):
        input_text = "```\n**also not bold**\n```"
        assert convert_markdown_to_mrkdwn(input_text) == input_text


class TestMarkdownShimNonString:
    def test_dict_untouched(self):
        # The shim should never inspect structured payloads
        result = convert_markdown_to_mrkdwn({"blocks": [{"type": "section"}]})
        assert result == {"blocks": [{"type": "section"}]}

    def test_list_untouched(self):
        result = convert_markdown_to_mrkdwn([{"type": "section"}])
        assert result == [{"type": "section"}]


class TestMarkdownShimSingleAsteriskItalic:
    def test_single_asterisk_not_converted(self):
        # v1 limitation: single-asterisk italic is not auto-converted
        assert convert_markdown_to_mrkdwn("*italic*") == "*italic*"


class TestMarkdownShimPlaceholderSentinel:
    def test_sentinel_not_in_output(self):
        # Verify the __SHIM_PH_N__ markers are fully restored
        result = convert_markdown_to_mrkdwn("`**not bold**`")
        assert "__SHIM_PH_" not in result

    def test_sentinel_not_in_output_fenced(self):
        input_text = "```\n**also not bold**\n```"
        result = convert_markdown_to_mrkdwn(input_text)
        assert "__SHIM_PH_" not in result

    def test_fenced_code_with_slack_link_no_sentinel(self):
        # Regression: fenced code block containing existing Slack link must
        # not leak __SHIM_PH_N__ markers after restoration (reverse order fix).
        input_text = "```\n<https://x|y>\n```"
        result = convert_markdown_to_mrkdwn(input_text)
        assert "__SHIM_PH_" not in result
        assert result == input_text

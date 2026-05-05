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
        # Verify the placeholder markers are fully restored
        result = convert_markdown_to_mrkdwn("`**not bold**`")
        assert "\x00SHIM_PH_" not in result
        assert "__SHIM_PH_" not in result

    def test_sentinel_not_in_output_fenced(self):
        input_text = "```\n**also not bold**\n```"
        result = convert_markdown_to_mrkdwn(input_text)
        assert "\x00SHIM_PH_" not in result
        assert "__SHIM_PH_" not in result

    def test_fenced_code_with_slack_link_no_sentinel(self):
        # Regression: fenced code block containing existing Slack link must
        # not leak placeholder markers after restoration (reverse order fix).
        input_text = "```\n<https://x|y>\n```"
        result = convert_markdown_to_mrkdwn(input_text)
        assert "\x00SHIM_PH_" not in result
        assert result == input_text

    def test_user_input_with_legacy_sentinel_string_not_corrupted(self):
        # Regression: user input containing the literal old-style sentinel
        # __SHIM_PH_0__ must not be treated as a placeholder. NUL-byte
        # sentinels make collisions impossible in practice.
        input_text = "see __SHIM_PH_0__ in the docs"
        result = convert_markdown_to_mrkdwn(input_text)
        # The double-underscore bold rule still converts __SHIM_PH_0__ to
        # *SHIM_PH_0* (that's the bold behavior, not corruption), but the
        # NUL-sentinel cannot be spoofed.
        assert "\x00" not in result


class TestMarkdownShimBoldItalic:
    def test_triple_asterisk_collapsed_to_bold(self):
        # AI agents often emit ***critical*** for emphasis. The shim
        # collapses to Slack bold rather than producing literal `**critical**`.
        assert convert_markdown_to_mrkdwn("***critical***") == "*critical*"

    def test_triple_underscore_collapsed_to_bold(self):
        assert convert_markdown_to_mrkdwn("___critical___") == "*critical*"

    def test_triple_asterisk_in_sentence(self):
        assert convert_markdown_to_mrkdwn("alert ***high*** priority") == "alert *high* priority"


class TestMarkdownShimInputCap:
    def test_long_input_returned_unchanged(self):
        # Defensive: inputs longer than 10_000 chars are returned unchanged
        # to avoid pathological regex backtracking on attacker-controlled text.
        # Slack section blocks are 3000 chars anyway, so legitimate text won't
        # hit this cap.
        long_input = "**bold**" + ("[" * 11_000)
        result = convert_markdown_to_mrkdwn(long_input)
        assert result == long_input  # not converted because over the cap

    def test_input_just_under_cap_still_converts(self):
        prefix = "x" * 9_990
        result = convert_markdown_to_mrkdwn(prefix + "**b**")
        assert result == prefix + "*b*"

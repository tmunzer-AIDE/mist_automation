"""
Unit tests for executor service helper functions.

Tests for module-level pure/near-pure functions: _sanitize_name and _sanitize_execution_error.
"""

import asyncio

import httpx
import pytest

from app.core.exceptions import MistAutomationException, WorkflowExecutionException
from app.modules.automation.services.executor_service import (
    _sanitize_execution_error,
    _sanitize_name,
)

pytestmark = pytest.mark.unit


# ── _sanitize_name ───────────────────────────────────────────────────────────


class TestSanitizeName:
    """Tests for _sanitize_name(name) — converts non-alphanumeric chars to underscores."""

    def test_spaces_to_underscores(self):
        assert _sanitize_name("My Node Name") == "My_Node_Name"

    def test_special_chars_to_underscores(self):
        assert _sanitize_name("node!@#$%^&*()") == "node__________"

    def test_alphanumeric_preserved(self):
        assert _sanitize_name("Node123") == "Node123"

    def test_underscores_preserved(self):
        assert _sanitize_name("my_node_1") == "my_node_1"

    def test_empty_string(self):
        assert _sanitize_name("") == ""

    def test_mixed_special_and_normal(self):
        assert _sanitize_name("Get AP-01 Status") == "Get_AP_01_Status"

    def test_dots_to_underscores(self):
        assert _sanitize_name("api.v1.sites") == "api_v1_sites"

    def test_hyphens_to_underscores(self):
        assert _sanitize_name("my-node-name") == "my_node_name"

    def test_only_special_chars(self):
        assert _sanitize_name("!@#") == "___"

    def test_unicode_chars_to_underscores(self):
        """Non-ASCII characters are not in [a-zA-Z0-9_], so they become underscores."""
        assert _sanitize_name("noeud_reseau") == "noeud_reseau"
        result = _sanitize_name("node_\u00e9")
        assert result == "node__"


# ── _sanitize_execution_error ────────────────────────────────────────────────


class TestSanitizeExecutionError:
    """Tests for _sanitize_execution_error(exc) — produces user-safe error messages."""

    def test_asyncio_timeout_error(self):
        exc = asyncio.TimeoutError()
        assert _sanitize_execution_error(exc) == "Operation timed out"

    def test_key_error_no_key_name_leaked(self):
        exc = KeyError("secret_field")
        result = _sanitize_execution_error(exc)
        assert result == "Missing required configuration key"
        assert "secret_field" not in result

    def test_value_error_returns_message(self):
        exc = ValueError("some error msg")
        assert _sanitize_execution_error(exc) == "some error msg"

    def test_type_error_returns_message(self):
        exc = TypeError("type error")
        assert _sanitize_execution_error(exc) == "type error"

    def test_generic_exception_truncated_to_200(self):
        long_msg = "x" * 300
        exc = Exception(long_msg)
        result = _sanitize_execution_error(exc)
        assert len(result) == 200
        # No trailing "..." appended — just a raw slice
        assert result == long_msg[:200]

    def test_generic_exception_under_200_not_truncated(self):
        exc = Exception("internal path /app/foo.py")
        result = _sanitize_execution_error(exc)
        assert result == "internal path /app/foo.py"

    def test_httpx_connect_error(self):
        exc = httpx.ConnectError("Connection refused")
        result = _sanitize_execution_error(exc)
        assert result == "Failed to connect to external service"

    def test_httpx_http_status_error(self):
        response = httpx.Response(status_code=403, request=httpx.Request("GET", "https://api.example.com"))
        exc = httpx.HTTPStatusError("Forbidden", request=response.request, response=response)
        result = _sanitize_execution_error(exc)
        assert result == "HTTP 403 from external API"

    def test_httpx_timeout_exception(self):
        exc = httpx.ReadTimeout("read timed out")
        result = _sanitize_execution_error(exc)
        assert result == "Request to external service timed out"

    def test_mist_automation_exception(self):
        exc = MistAutomationException("Something went wrong", status_code=500)
        result = _sanitize_execution_error(exc)
        assert result == "Something went wrong"

    def test_mist_automation_exception_subclass(self):
        exc = WorkflowExecutionException("Workflow failed", workflow_id="wf-123")
        result = _sanitize_execution_error(exc)
        assert result == "Workflow failed"
        # Internal details should not leak
        assert "wf-123" not in result

    def test_value_error_long_message_truncated(self):
        long_msg = "v" * 300
        exc = ValueError(long_msg)
        result = _sanitize_execution_error(exc)
        assert len(result) == 200

    def test_type_error_long_message_truncated(self):
        long_msg = "t" * 250
        exc = TypeError(long_msg)
        result = _sanitize_execution_error(exc)
        assert len(result) == 200

    def test_key_error_empty_key(self):
        exc = KeyError("")
        result = _sanitize_execution_error(exc)
        assert result == "Missing required configuration key"

    def test_generic_exception_exactly_200_chars(self):
        msg = "a" * 200
        exc = Exception(msg)
        result = _sanitize_execution_error(exc)
        assert result == msg
        assert len(result) == 200

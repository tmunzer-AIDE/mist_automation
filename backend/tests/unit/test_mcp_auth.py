"""Unit tests for the MCP auth middleware token extraction."""

import pytest

from app.modules.mcp_server.auth_middleware import MCPAuthMiddleware


@pytest.mark.unit
class TestMcpAuthExtractToken:
    def test_extract_valid_bearer(self):
        scope = {"headers": [(b"authorization", b"Bearer abc123")]}
        assert MCPAuthMiddleware._extract_bearer_token(scope) == "abc123"

    def test_extract_missing_header(self):
        scope = {"headers": []}
        assert MCPAuthMiddleware._extract_bearer_token(scope) is None

    def test_extract_no_headers_key(self):
        scope = {}
        assert MCPAuthMiddleware._extract_bearer_token(scope) is None

    def test_extract_non_bearer(self):
        scope = {"headers": [(b"authorization", b"Basic abc123")]}
        assert MCPAuthMiddleware._extract_bearer_token(scope) is None

    def test_extract_bearer_case_insensitive(self):
        scope = {"headers": [(b"authorization", b"bearer token123")]}
        assert MCPAuthMiddleware._extract_bearer_token(scope) == "token123"

    def test_extract_with_extra_whitespace(self):
        scope = {"headers": [(b"authorization", b"Bearer   token123  ")]}
        assert MCPAuthMiddleware._extract_bearer_token(scope) == "token123"

    def test_extract_empty_token_after_bearer(self):
        scope = {"headers": [(b"authorization", b"Bearer ")]}
        # "Bearer " with nothing after → strip yields ""
        assert MCPAuthMiddleware._extract_bearer_token(scope) == ""

    def test_ignores_other_headers(self):
        scope = {
            "headers": [
                (b"content-type", b"application/json"),
                (b"authorization", b"Bearer mytoken"),
                (b"x-request-id", b"123"),
            ]
        }
        assert MCPAuthMiddleware._extract_bearer_token(scope) == "mytoken"

    def test_first_authorization_header_wins(self):
        scope = {
            "headers": [
                (b"authorization", b"Bearer first"),
                (b"authorization", b"Bearer second"),
            ]
        }
        # Implementation iterates headers and returns on first match
        assert MCPAuthMiddleware._extract_bearer_token(scope) == "first"

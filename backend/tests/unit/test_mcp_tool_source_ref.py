"""Unit tests for MCP digital_twin tool source_ref resolution."""

# Import the server module first to prime circular imports between
# mcp_server.server and mcp_server.tools.*.
from app.modules.mcp_server import server  # noqa: F401
from app.modules.mcp_server.tools import digital_twin as twin_tool

_resolve_source_ref = getattr(twin_tool, "_resolve_source_ref")


def test_resolve_none_defaults_to_internal_chat():
    assert _resolve_source_ref(None) == "Internal Chat"


def test_resolve_empty_string_defaults_to_internal_chat():
    assert _resolve_source_ref("") == "Internal Chat"


def test_resolve_whitespace_defaults_to_internal_chat():
    assert _resolve_source_ref("   ") == "Internal Chat"


def test_resolve_external_client_name():
    assert _resolve_source_ref("Claude Desktop") == "Claude Desktop"


def test_resolve_trims_whitespace():
    assert _resolve_source_ref("  Cursor  ") == "Cursor"

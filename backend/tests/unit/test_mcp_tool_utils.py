"""Unit tests for shared MCP tool validation utilities."""

import pytest

from app.modules.mcp_server.tools.utils import endpoint_has_placeholder, is_placeholder, is_uuid


@pytest.mark.unit
class TestMcpToolUtils:
    def test_is_placeholder_detects_common_patterns(self):
        assert is_placeholder("{site_id}") is True
        assert is_placeholder("<device_id>") is True
        assert is_placeholder(":session_id") is True
        assert is_placeholder("{{org_id}}") is True
        assert is_placeholder("%7Bsite_id%7D") is True

    def test_is_placeholder_ignores_regular_values(self):
        assert is_placeholder("0fdb73c9-2c77-4b45-8f5b-4b30f5d6df7c") is False
        assert is_placeholder("guest-wlan") is False
        assert is_placeholder("") is False
        assert is_placeholder(None) is False

    def test_endpoint_has_placeholder(self):
        assert endpoint_has_placeholder("/api/v1/sites/{site_id}/devices/x") is True
        assert endpoint_has_placeholder("/api/v1/sites/:site_id/devices/x") is True
        assert endpoint_has_placeholder("/api/v1/sites/<site_id>/devices/x") is True
        assert endpoint_has_placeholder("/api/v1/sites/%7Bsite_id%7D/devices/x") is True
        assert endpoint_has_placeholder("/api/v1/sites/site-1/devices/dev-1") is False

    def test_is_uuid(self):
        assert is_uuid("0fdb73c9-2c77-4b45-8f5b-4b30f5d6df7c") is True
        assert is_uuid("DNT-NRT") is False
        assert is_uuid("") is False
        assert is_uuid(None) is False

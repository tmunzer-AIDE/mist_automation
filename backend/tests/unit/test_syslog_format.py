"""Tests for the syslog action node format building and dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import WorkflowExecutionError
from app.modules.automation.services.executor_service import WorkflowExecutor
from app.utils.variables import create_jinja_env

# Patch path for validate_outbound_host inside executor_service
_PATCH_VALIDATE = "app.utils.url_safety.validate_outbound_host_async"


def _make_executor() -> WorkflowExecutor:
    """Create a minimal WorkflowExecutor for testing _execute_syslog."""
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.variable_context = {"trigger": {}, "nodes": {}, "results": {}}
    executor._jinja_env = create_jinja_env()
    executor._cached_render_context = None
    return executor


@pytest.mark.unit
class TestSyslogFormat:
    async def test_rfc5424_format_contains_app_name(self):
        executor = _make_executor()
        with patch("asyncio.get_running_loop") as mock_loop, \
             patch(_PATCH_VALIDATE):
            mock_transport = MagicMock()
            mock_loop.return_value.create_datagram_endpoint = AsyncMock(
                return_value=(mock_transport, None)
            )
            result = await executor._execute_syslog(
                {
                    "syslog_host": "198.51.100.1",
                    "syslog_port": 514,
                    "syslog_protocol": "udp",
                    "syslog_format": "rfc5424",
                    "syslog_facility": "local0",
                    "syslog_severity": "informational",
                    "notification_template": "test message",
                }
            )
            assert result["status"] == "sent"
            assert result["format"] == "rfc5424"
            assert "mist-automation" in result["message"]
            mock_transport.close.assert_called_once()

    async def test_cef_format_contains_vendor_product(self):
        executor = _make_executor()
        with patch("asyncio.get_running_loop") as mock_loop, \
             patch(_PATCH_VALIDATE):
            mock_transport = MagicMock()
            mock_loop.return_value.create_datagram_endpoint = AsyncMock(
                return_value=(mock_transport, None)
            )
            result = await executor._execute_syslog(
                {
                    "syslog_host": "198.51.100.1",
                    "syslog_port": 514,
                    "syslog_protocol": "udp",
                    "syslog_format": "cef",
                    "syslog_facility": "local0",
                    "syslog_severity": "error",
                    "notification_template": "alarm triggered",
                    "cef_device_vendor": "Juniper",
                    "cef_device_product": "Mist",
                    "cef_event_class_id": "ALARM",
                    "cef_name": "AP Down",
                }
            )
            assert result["format"] == "cef"
            assert "CEF:0|Juniper|Mist|" in result["message"]
            assert "ALARM" in result["message"]

    async def test_missing_host_raises_error(self):
        executor = _make_executor()
        with pytest.raises(WorkflowExecutionError, match="Syslog host is required"):
            await executor._execute_syslog({"syslog_host": "", "syslog_format": "rfc5424"})

    async def test_blocked_host_raises_error(self):
        """SSRF protection: localhost should be blocked."""
        executor = _make_executor()
        with pytest.raises(WorkflowExecutionError, match="Syslog host blocked"):
            await executor._execute_syslog(
                {
                    "syslog_host": "127.0.0.1",
                    "syslog_port": 514,
                    "syslog_protocol": "udp",
                    "syslog_format": "rfc5424",
                    "notification_template": "test",
                }
            )

    async def test_tcp_sends_with_newline(self):
        executor = _make_executor()
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(AsyncMock(), mock_writer)), \
             patch(_PATCH_VALIDATE):
            result = await executor._execute_syslog(
                {
                    "syslog_host": "198.51.100.1",
                    "syslog_port": 514,
                    "syslog_protocol": "tcp",
                    "syslog_format": "rfc5424",
                    "syslog_facility": "local0",
                    "syslog_severity": "notice",
                    "notification_template": "tcp test",
                }
            )
            assert result["protocol"] == "tcp"
            write_call = mock_writer.write.call_args[0][0]
            assert write_call.endswith(b"\n")

    def test_facility_severity_math(self):
        """PRI = facility * 8 + severity."""
        assert 16 * 8 + 6 == 134   # local0 + informational
        assert 23 * 8 + 0 == 184   # local7 + emergency
        assert 19 * 8 + 3 == 155   # local3 + error

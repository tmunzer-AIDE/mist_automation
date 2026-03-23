"""Unit tests for the workflow failure notification helper."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.automation.models.execution import ExecutionStatus
from app.modules.automation.models.workflow import FailureNotificationConfig, NotificationChannel
from app.modules.automation.workers.notification_helper import (
    _build_context,
    _build_message,
    notify_workflow_failure,
)


def _mock_workflow(name="Test WF", wf_id="wf123"):
    workflow = MagicMock()
    workflow.name = name
    workflow.id = wf_id
    return workflow


def _mock_execution(
    ex_id="ex456",
    status=ExecutionStatus.FAILED,
    error="Something broke",
    duration_ms=1234,
    nodes_executed=5,
    nodes_succeeded=3,
    nodes_failed=2,
):
    execution = MagicMock()
    execution.id = ex_id
    execution.status = status
    execution.error = error
    execution.duration_ms = duration_ms
    execution.nodes_executed = nodes_executed
    execution.nodes_succeeded = nodes_succeeded
    execution.nodes_failed = nodes_failed
    execution.started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    execution.trigger_type = "webhook"
    return execution


@pytest.mark.unit
class TestBuildContext:
    def test_context_fields(self):
        workflow = _mock_workflow()
        execution = _mock_execution()
        ctx = _build_context(workflow, execution)
        assert ctx["workflow_name"] == "Test WF"
        assert ctx["workflow_id"] == "wf123"
        assert ctx["execution_id"] == "ex456"
        assert ctx["status"] == "failed"
        assert ctx["error"] == "Something broke"
        assert ctx["duration_ms"] == 1234
        assert ctx["nodes_executed"] == 5
        assert ctx["nodes_succeeded"] == 3
        assert ctx["nodes_failed"] == 2
        assert ctx["trigger_type"] == "webhook"

    def test_context_none_error(self):
        execution = _mock_execution(error=None, duration_ms=None)
        ctx = _build_context(_mock_workflow(), execution)
        assert ctx["error"] is None
        assert ctx["duration_ms"] == 0

    def test_context_string_status(self):
        execution = _mock_execution()
        execution.status = "custom_status"
        ctx = _build_context(_mock_workflow(), execution)
        assert ctx["status"] == "custom_status"


@pytest.mark.unit
class TestBuildMessage:
    def test_message_contains_workflow_name(self):
        ctx = {
            "workflow_name": "My WF",
            "status": "failed",
            "duration_ms": 100,
            "nodes_executed": 3,
            "nodes_failed": 1,
            "error": "timeout",
        }
        msg = _build_message(ctx)
        assert "My WF" in msg
        assert "timeout" in msg
        assert "3 executed" in msg
        assert "1 failed" in msg

    def test_message_no_error_omits_error_line(self):
        ctx = {
            "workflow_name": "WF",
            "status": "failed",
            "duration_ms": 0,
            "nodes_executed": 0,
            "nodes_failed": 0,
            "error": None,
        }
        msg = _build_message(ctx)
        assert "Error:" not in msg

    def test_message_with_error_includes_error_line(self):
        ctx = {
            "workflow_name": "WF",
            "status": "failed",
            "duration_ms": 50,
            "nodes_executed": 2,
            "nodes_failed": 1,
            "error": "connection refused",
        }
        msg = _build_message(ctx)
        assert "Error: connection refused" in msg


@pytest.mark.unit
class TestNotifyWorkflowFailure:
    async def test_disabled_config_returns_early(self):
        workflow = _mock_workflow()
        workflow.failure_notification = FailureNotificationConfig(
            enabled=False, channel=NotificationChannel.SLACK
        )
        execution = _mock_execution()
        # Should not raise, just return
        await notify_workflow_failure(workflow, execution)

    async def test_none_config_returns_early(self):
        workflow = _mock_workflow()
        workflow.failure_notification = None
        execution = _mock_execution()
        await notify_workflow_failure(workflow, execution)

    async def test_slack_notification_called(self):
        workflow = _mock_workflow()
        workflow.failure_notification = FailureNotificationConfig(
            enabled=True,
            channel=NotificationChannel.SLACK,
            slack_webhook_url="https://hooks.slack.com/test",
        )
        execution = _mock_execution()

        with patch("app.modules.automation.workers.notification_helper.NotificationService") as MockNS:
            mock_svc = AsyncMock()
            mock_svc.close = AsyncMock()
            MockNS.return_value = mock_svc

            await notify_workflow_failure(workflow, execution)

            mock_svc.send_slack_notification.assert_called_once()
            mock_svc.close.assert_called_once()

    async def test_exception_swallowed(self):
        workflow = _mock_workflow()
        workflow.failure_notification = FailureNotificationConfig(
            enabled=True, channel=NotificationChannel.SLACK
        )
        execution = _mock_execution()

        with patch("app.modules.automation.workers.notification_helper.NotificationService") as MockNS:
            mock_svc = AsyncMock()
            mock_svc.send_slack_notification.side_effect = Exception("Network error")
            mock_svc.close = AsyncMock()
            MockNS.return_value = mock_svc

            # Should NOT raise — exceptions are swallowed
            await notify_workflow_failure(workflow, execution)

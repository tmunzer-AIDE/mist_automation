"""Unit tests for the execution cleanup worker."""

import pytest
from datetime import datetime, timedelta, timezone

from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
from app.modules.automation.workers.cleanup_worker import cleanup_old_executions


@pytest.mark.unit
class TestCleanupWorker:
    async def test_deletes_old_executions(self, test_db):
        # Create an execution older than the default retention (90 days)
        old = WorkflowExecution(
            workflow_id="000000000000000000000001",
            workflow_name="Old WF",
            trigger_type="manual",
            started_at=datetime.now(timezone.utc) - timedelta(days=200),
            status=ExecutionStatus.SUCCESS,
        )
        await old.insert()

        # Create a recent execution
        new = WorkflowExecution(
            workflow_id="000000000000000000000001",
            workflow_name="New WF",
            trigger_type="manual",
            started_at=datetime.now(timezone.utc) - timedelta(days=10),
            status=ExecutionStatus.SUCCESS,
        )
        await new.insert()

        result = await cleanup_old_executions()
        assert result["deleted_count"] == 1

        remaining = await WorkflowExecution.find().to_list()
        assert len(remaining) == 1
        assert remaining[0].workflow_name == "New WF"

    async def test_no_executions_to_delete(self, test_db):
        result = await cleanup_old_executions()
        assert result["deleted_count"] == 0

    async def test_boundary_execution_not_deleted(self, test_db):
        # Execution exactly at retention boundary should NOT be deleted
        boundary = WorkflowExecution(
            workflow_id="000000000000000000000001",
            workflow_name="Boundary WF",
            trigger_type="manual",
            started_at=datetime.now(timezone.utc) - timedelta(days=89),
            status=ExecutionStatus.SUCCESS,
        )
        await boundary.insert()

        result = await cleanup_old_executions()
        assert result["deleted_count"] == 0

        remaining = await WorkflowExecution.find().to_list()
        assert len(remaining) == 1

    async def test_returns_retention_days(self, test_db):
        result = await cleanup_old_executions()
        assert "retention_days" in result
        assert isinstance(result["retention_days"], int)

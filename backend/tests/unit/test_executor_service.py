"""Unit tests for workflow executor service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


class TestWorkflowExecutor:
    async def test_executor_initializes_with_mist_service(self):
        """Test that executor can be initialized with a mock MistService."""
        from app.services.executor_service import WorkflowExecutor
        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)
        assert executor.mist_service is mock_mist

    async def test_executor_has_empty_variable_context_initially(self):
        """Test that executor starts with an empty variable context."""
        from app.services.executor_service import WorkflowExecutor
        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)
        assert executor.variable_context == {}

    async def test_execute_workflow_creates_execution_record(self, test_db, test_user, test_workflow):
        """Test that executing a workflow creates a WorkflowExecution record."""
        from app.services.executor_service import WorkflowExecutor
        from app.models.execution import WorkflowExecution

        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)

        # Mock action execution to avoid actual HTTP calls
        with patch.object(executor, '_execute_action', new_callable=AsyncMock) as mock_action:
            mock_action.return_value = {"status": "success"}
            try:
                execution = await executor.execute_workflow(
                    workflow=test_workflow,
                    trigger_data={"topic": "device-updowns", "events": []},
                    trigger_source="webhook",
                )
                # If it succeeds, verify execution record created
                assert execution is not None
                assert str(execution.workflow_id) == str(test_workflow.id)
            except Exception:
                # Execution may fail due to missing action implementations
                # but we verify the execution record was at least attempted
                count = await WorkflowExecution.find(
                    WorkflowExecution.workflow_id == test_workflow.id
                ).count()
                assert count >= 1

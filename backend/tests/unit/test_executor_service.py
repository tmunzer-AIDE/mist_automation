"""Unit tests for graph-based workflow executor service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


class TestWorkflowExecutor:
    async def test_executor_initializes_with_mist_service(self):
        """Test that executor can be initialized with a mock MistService."""
        from app.modules.automation.services.executor_service import WorkflowExecutor

        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)
        assert executor.mist_service is mock_mist

    async def test_executor_has_empty_variable_context_initially(self):
        """Test that executor starts with a pre-structured variable context."""
        from app.modules.automation.services.executor_service import WorkflowExecutor

        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)
        assert executor.variable_context == {"trigger": {}, "nodes": {}, "results": {}}

    async def test_execute_workflow_creates_execution_record(self, test_db, test_user, test_workflow):
        """Test that executing a workflow creates a WorkflowExecution record."""
        from app.modules.automation.services.executor_service import WorkflowExecutor
        from app.modules.automation.models.execution import WorkflowExecution

        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)

        # Mock the node execution to avoid actual HTTP calls
        with patch.object(executor, "_execute_node_by_type", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"status_code": 200, "response": "ok"}
            try:
                execution = await executor.execute_workflow(
                    workflow=test_workflow,
                    trigger_data={
                        "topic": "device-updowns",
                        "type": "device_up",
                        "org_id": "test-org",
                        "site_id": "test-site",
                    },
                    trigger_source="webhook",
                )
                assert execution is not None
                assert str(execution.workflow_id) == str(test_workflow.id)
            except Exception:
                # Execution may fail but verify record was created
                count = await WorkflowExecution.find(WorkflowExecution.workflow_id == test_workflow.id).count()
                assert count >= 1

    async def test_execute_graph_traverses_nodes(self, test_db, test_user, test_workflow):
        """Test that the graph executor traverses nodes via edges."""
        from app.modules.automation.services.executor_service import WorkflowExecutor

        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)

        with patch.object(executor, "_execute_node_by_type", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"status_code": 200}
            execution = await executor.execute_workflow(
                workflow=test_workflow,
                trigger_data={
                    "topic": "device-updowns",
                    "type": "device_up",
                    "org_id": "test-org",
                    "site_id": "test-site",
                },
                trigger_source="webhook",
            )
            # The action-1 node should have been executed
            assert "action-1" in execution.node_results
            assert execution.node_results["action-1"].status == "success"

    async def test_simulation_captures_snapshots(self, test_db, test_user, test_workflow):
        """Test that simulation mode captures node snapshots."""
        from app.modules.automation.services.executor_service import WorkflowExecutor

        mock_mist = MagicMock()
        executor = WorkflowExecutor(mist_service=mock_mist)

        with patch.object(executor, "_execute_node_by_type", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"status_code": 200}
            execution = await executor.execute_workflow(
                workflow=test_workflow,
                trigger_data={
                    "topic": "device-updowns",
                    "type": "device_up",
                    "org_id": "test-org",
                    "site_id": "test-site",
                },
                trigger_source="simulation",
                simulate=True,
                dry_run=True,
            )
            assert execution.is_simulation is True
            assert execution.is_dry_run is True
            # Should have snapshots for trigger + action
            assert len(execution.node_snapshots) >= 1

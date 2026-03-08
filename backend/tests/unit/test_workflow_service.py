"""Unit tests for workflow service."""
import pytest
from bson import ObjectId

pytestmark = pytest.mark.asyncio


class TestCreateWorkflow:
    async def test_create_valid_workflow(self, test_db, test_user):
        from app.services.workflow_service import WorkflowService
        from app.models.workflow import WorkflowTrigger, TriggerType, WorkflowAction, ActionType
        service = WorkflowService()
        trigger = WorkflowTrigger(type=TriggerType.WEBHOOK, webhook_type="device-updowns")
        actions = [WorkflowAction(name="notify", type=ActionType.WEBHOOK, webhook_url="http://example.com")]
        wf = await service.create_workflow(
            name="My Workflow",
            trigger=trigger,
            created_by=test_user.id,
            actions=actions,
        )
        assert wf.name == "My Workflow"
        assert str(wf.created_by) == str(test_user.id)

    async def test_create_workflow_invalid_cron_raises(self, test_db, test_user):
        from app.services.workflow_service import WorkflowService
        from app.models.workflow import WorkflowTrigger, TriggerType, WorkflowAction, ActionType
        from app.core.exceptions import ValidationError
        service = WorkflowService()
        trigger = WorkflowTrigger(type=TriggerType.CRON, cron_expression="invalid-cron")
        actions = [WorkflowAction(name="notify", type=ActionType.WEBHOOK, webhook_url="http://example.com")]
        with pytest.raises((ValidationError, Exception)):
            await service.create_workflow(
                name="Cron Workflow",
                trigger=trigger,
                created_by=test_user.id,
                actions=actions,
            )

    async def test_create_workflow_no_actions_raises(self, test_db, test_user):
        from app.services.workflow_service import WorkflowService
        from app.models.workflow import WorkflowTrigger, TriggerType
        from app.core.exceptions import ValidationError
        service = WorkflowService()
        trigger = WorkflowTrigger(type=TriggerType.WEBHOOK, webhook_type="device-updowns")
        with pytest.raises((ValidationError, Exception)):
            await service.create_workflow(
                name="No Actions Workflow",
                trigger=trigger,
                created_by=test_user.id,
                actions=[],
            )


class TestListWorkflows:
    async def test_list_workflows_pagination(self, test_db, test_user, test_workflow):
        from app.services.workflow_service import WorkflowService
        service = WorkflowService()
        result = await service.list_workflows(test_user, skip=0, limit=10)
        assert isinstance(result, (list, tuple, dict))

    async def test_list_workflows_returns_created_workflow(self, test_db, test_user, test_workflow):
        from app.services.workflow_service import WorkflowService
        service = WorkflowService()
        workflows, total = await service.list_workflows(test_user, skip=0, limit=10)
        assert total >= 1
        workflow_ids = [str(wf.id) for wf in workflows]
        assert str(test_workflow.id) in workflow_ids

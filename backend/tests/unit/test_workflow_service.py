"""Unit tests for workflow service — graph model."""
import pytest
from bson import ObjectId

pytestmark = pytest.mark.asyncio


def _make_trigger_node():
    from app.modules.automation.models.workflow import WorkflowNode, NodePosition, NodePort

    return WorkflowNode(
        id="trigger-1",
        type="trigger",
        name="Trigger",
        position=NodePosition(x=400, y=80),
        config={"trigger_type": "webhook", "webhook_type": "device-updowns"},
        output_ports=[NodePort(id="default")],
    )


def _make_action_node(id="action-1"):
    from app.modules.automation.models.workflow import WorkflowNode, NodePosition, NodePort

    return WorkflowNode(
        id=id,
        type="webhook",
        name="notify",
        position=NodePosition(x=400, y=240),
        config={"webhook_url": "http://example.com"},
        output_ports=[NodePort(id="default")],
    )


def _make_edge(src="trigger-1", tgt="action-1"):
    from app.modules.automation.models.workflow import WorkflowEdge

    return WorkflowEdge(
        id=f"edge-{src}-{tgt}",
        source_node_id=src,
        source_port_id="default",
        target_node_id=tgt,
        target_port_id="input",
    )


class TestCreateWorkflow:
    async def test_create_valid_workflow(self, test_db, test_user):
        from app.modules.automation.services.workflow_service import WorkflowService

        trigger = _make_trigger_node()
        action = _make_action_node()
        edge = _make_edge()

        wf = await WorkflowService.create_workflow(
            name="My Workflow",
            created_by=test_user.id,
            nodes=[trigger, action],
            edges=[edge],
        )
        assert wf.name == "My Workflow"
        assert str(wf.created_by) == str(test_user.id)
        assert len(wf.nodes) == 2
        assert len(wf.edges) == 1

    async def test_create_workflow_no_trigger_raises(self, test_db, test_user):
        from app.modules.automation.services.workflow_service import WorkflowService
        from app.core.exceptions import ValidationError

        action = _make_action_node()

        with pytest.raises(ValidationError):
            await WorkflowService.create_workflow(
                name="No Trigger",
                created_by=test_user.id,
                nodes=[action],
                edges=[],
            )


class TestListWorkflows:
    async def test_list_workflows_pagination(self, test_db, test_user, test_workflow):
        from app.modules.automation.services.workflow_service import WorkflowService

        result = await WorkflowService.list_workflows(test_user, skip=0, limit=10)
        assert isinstance(result, tuple)

    async def test_list_workflows_returns_created_workflow(self, test_db, test_user, test_workflow):
        from app.modules.automation.services.workflow_service import WorkflowService

        workflows, total = await WorkflowService.list_workflows(test_user, skip=0, limit=10)
        assert total >= 1
        workflow_ids = [str(wf.id) for wf in workflows]
        assert str(test_workflow.id) in workflow_ids

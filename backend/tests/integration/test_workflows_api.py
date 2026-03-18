"""Integration tests for workflows API."""
import pytest

pytestmark = pytest.mark.asyncio


class TestListWorkflows:
    async def test_list_workflows_returns_list(self, client, test_workflow):
        response = await client.get("/api/v1/workflows")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data or isinstance(data, list)

    async def test_list_workflows_includes_test_workflow(self, client, test_workflow):
        response = await client.get("/api/v1/workflows")
        assert response.status_code == 200
        data = response.json()
        workflows = data.get("workflows", data) if isinstance(data, dict) else data
        ids = [str(wf.get("id", "")) for wf in workflows]
        assert str(test_workflow.id) in ids


class TestCreateWorkflow:
    async def test_create_workflow(self, client):
        payload = {
            "name": "API Test Workflow",
            "nodes": [
                {
                    "id": "trigger-1",
                    "type": "trigger",
                    "name": "Trigger",
                    "position": {"x": 400, "y": 80},
                    "config": {"trigger_type": "webhook", "webhook_type": "device-updowns"},
                    "output_ports": [{"id": "default", "label": "", "type": "default"}],
                },
                {
                    "id": "action-1",
                    "type": "webhook",
                    "name": "notify",
                    "position": {"x": 400, "y": 240},
                    "config": {"webhook_url": "http://example.com"},
                    "output_ports": [{"id": "default", "label": "", "type": "default"}],
                },
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "source_node_id": "trigger-1",
                    "source_port_id": "default",
                    "target_node_id": "action-1",
                    "target_port_id": "input",
                },
            ],
        }
        response = await client.post("/api/v1/workflows", json=payload)
        assert response.status_code in (200, 201)

    async def test_create_workflow_missing_fields_returns_422(self, client):
        response = await client.post("/api/v1/workflows", json={})
        assert response.status_code == 422


class TestGetWorkflow:
    async def test_get_existing_workflow(self, client, test_workflow):
        response = await client.get(f"/api/v1/workflows/{test_workflow.id}")
        assert response.status_code == 200

    async def test_get_unknown_workflow_returns_404(self, client):
        from bson import ObjectId
        response = await client.get(f"/api/v1/workflows/{ObjectId()}")
        assert response.status_code == 404


class TestDeleteWorkflow:
    async def test_delete_workflow(self, client, test_workflow):
        response = await client.delete(f"/api/v1/workflows/{test_workflow.id}")
        assert response.status_code in (200, 204)

    async def test_delete_again_returns_404(self, client, test_workflow):
        await client.delete(f"/api/v1/workflows/{test_workflow.id}")
        response = await client.delete(f"/api/v1/workflows/{test_workflow.id}")
        assert response.status_code == 404

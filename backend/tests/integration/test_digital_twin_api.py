"""Integration tests for Digital Twin REST API."""

import pytest

pytestmark = pytest.mark.asyncio


class TestListTwinSessions:
    async def test_list_empty(self, client):
        response = await client.get("/api/v1/digital-twin/sessions")
        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0


class TestGetTwinSession:
    async def test_not_found(self, client):
        from bson import ObjectId

        response = await client.get(f"/api/v1/digital-twin/sessions/{ObjectId()}")
        assert response.status_code == 404

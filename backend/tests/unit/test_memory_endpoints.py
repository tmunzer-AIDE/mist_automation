"""Unit tests for user memory API endpoints."""

import pytest


@pytest.mark.unit
class TestMemoryEndpoints:
    async def test_list_memories_empty(self, client):
        resp = await client.get("/api/v1/llm/memories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entries"] == []
        assert data["total"] == 0

    async def test_list_memories_with_entries(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        await MemoryEntry(user_id=test_user.id, key="k1", value="v1").insert()
        await MemoryEntry(user_id=test_user.id, key="k2", value="v2", category="network").insert()
        resp = await client.get("/api/v1/llm/memories")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    async def test_list_filter_by_category(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        await MemoryEntry(user_id=test_user.id, key="k1", value="v1", category="network").insert()
        await MemoryEntry(user_id=test_user.id, key="k2", value="v2", category="preference").insert()
        resp = await client.get("/api/v1/llm/memories?category=network")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_get_memory(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        entry = MemoryEntry(user_id=test_user.id, key="k1", value="v1")
        await entry.insert()
        resp = await client.get(f"/api/v1/llm/memories/{entry.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "k1"
        assert data["value"] == "v1"

    async def test_get_memory_not_found(self, client):
        resp = await client.get("/api/v1/llm/memories/000000000000000000000000")
        assert resp.status_code == 404

    async def test_update_memory(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        entry = MemoryEntry(user_id=test_user.id, key="k1", value="old")
        await entry.insert()
        resp = await client.put(f"/api/v1/llm/memories/{entry.id}", json={"value": "new", "category": "network"})
        assert resp.status_code == 200
        assert resp.json()["value"] == "new"
        assert resp.json()["category"] == "network"

    async def test_update_memory_invalid_category(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        entry = MemoryEntry(user_id=test_user.id, key="k1", value="v1")
        await entry.insert()
        resp = await client.put(f"/api/v1/llm/memories/{entry.id}", json={"category": "invalid"})
        assert resp.status_code == 400

    async def test_delete_memory(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        entry = MemoryEntry(user_id=test_user.id, key="k1", value="v1")
        await entry.insert()
        resp = await client.delete(f"/api/v1/llm/memories/{entry.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert resp.json()["key"] == "k1"
        assert await MemoryEntry.get(entry.id) is None

    async def test_delete_all_memories(self, client, test_user):
        from app.modules.llm.models import MemoryEntry

        await MemoryEntry(user_id=test_user.id, key="k1", value="v1").insert()
        await MemoryEntry(user_id=test_user.id, key="k2", value="v2").insert()
        resp = await client.delete("/api/v1/llm/memories?confirm=true")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
        assert resp.json()["count"] == 2
        count = await MemoryEntry.find({"user_id": test_user.id}).count()
        assert count == 0

    async def test_delete_all_requires_confirm(self, client):
        resp = await client.delete("/api/v1/llm/memories")
        assert resp.status_code == 400

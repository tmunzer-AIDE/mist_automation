"""
Unit tests for memory MCP tool helper functions.

Tests the internal _store_memory, _recall_memory, _forget_memory functions
directly — no MCP protocol involved.
"""

import pytest
from fastmcp.exceptions import ToolError

from app.modules.llm.models import MemoryEntry
from app.modules.mcp_server.tools.memory import _forget_memory, _recall_memory, _store_memory


@pytest.mark.unit
class TestStoreMemory:
    """Tests for _store_memory helper."""

    async def test_store_new_entry(self, test_db, test_user):
        result = await _store_memory(
            user_id=str(test_user.id),
            key="wifi_ssid",
            value="The main office SSID is CorpNet-5G",
            category="network",
            thread_id="thread-abc",
        )
        assert "stored" in result.lower() or "saved" in result.lower()

        entry = await MemoryEntry.find_one(
            MemoryEntry.user_id == test_user.id,
            MemoryEntry.key == "wifi_ssid",
        )
        assert entry is not None
        assert entry.value == "The main office SSID is CorpNet-5G"
        assert entry.category == "network"
        assert entry.source_thread_id == "thread-abc"

    async def test_store_upsert_existing(self, test_db, test_user):
        await _store_memory(str(test_user.id), "fav_site", "HQ Floor 1", "general", None)
        await _store_memory(str(test_user.id), "fav_site", "HQ Floor 2", "preference", "t2")

        entries = await MemoryEntry.find(
            MemoryEntry.user_id == test_user.id,
            MemoryEntry.key == "fav_site",
        ).to_list()
        assert len(entries) == 1
        assert entries[0].value == "HQ Floor 2"
        assert entries[0].category == "preference"
        assert entries[0].source_thread_id == "t2"

    async def test_store_rejects_over_cap(self, test_db, test_user):
        # Fill 100 entries
        for i in range(100):
            entry = MemoryEntry(
                user_id=test_user.id,
                key=f"key_{i:03d}",
                value=f"value_{i}",
                category="general",
            )
            await entry.insert()

        with pytest.raises(ToolError, match="Memory limit"):
            await _store_memory(str(test_user.id), "one_more", "should fail", "general", None)

    async def test_store_validates_key_length(self, test_db, test_user):
        long_key = "k" * 101
        with pytest.raises(ToolError, match="Key too long"):
            await _store_memory(str(test_user.id), long_key, "val", "general", None)

    async def test_store_validates_value_length(self, test_db, test_user):
        long_value = "v" * 501
        with pytest.raises(ToolError, match="Value too long"):
            await _store_memory(str(test_user.id), "mykey", long_value, "general", None)

    async def test_store_rejects_invalid_category(self, test_db, test_user):
        with pytest.raises(ToolError, match="Invalid category"):
            await _store_memory(str(test_user.id), "test_key", "test_val", "invalid_cat", None)


@pytest.mark.unit
class TestRecallMemory:
    """Tests for _recall_memory helper."""

    async def test_recall_by_query(self, test_db, test_user):
        await _store_memory(str(test_user.id), "office_wifi", "CorpNet uses WPA3", "network", None)
        await _store_memory(str(test_user.id), "home_wifi", "HomeNet uses WPA2", "network", None)

        result = await _recall_memory(str(test_user.id), query="CorpNet", category=None)
        assert "office_wifi" in result
        assert "CorpNet" in result

    async def test_recall_by_category(self, test_db, test_user):
        await _store_memory(str(test_user.id), "pref1", "dark mode", "preference", None)
        await _store_memory(str(test_user.id), "net1", "subnet is 10.0.0.0/24", "network", None)

        result = await _recall_memory(str(test_user.id), query=None, category="preference")
        assert "pref1" in result
        assert "dark mode" in result
        assert "net1" not in result

    async def test_recall_recent_no_args(self, test_db, test_user):
        for i in range(5):
            await _store_memory(str(test_user.id), f"recent_{i}", f"value_{i}", "general", None)

        result = await _recall_memory(str(test_user.id), query=None, category=None)
        assert "recent_" in result

    async def test_recall_empty(self, test_db, test_user):
        result = await _recall_memory(str(test_user.id), query=None, category=None)
        assert result == "No memories found."


@pytest.mark.unit
class TestForgetMemory:
    """Tests for _forget_memory helper."""

    async def test_forget_existing(self, test_db, test_user):
        await _store_memory(str(test_user.id), "to_delete", "temp value", "general", None)

        result = await _forget_memory(str(test_user.id), "to_delete")
        assert "deleted" in result.lower() or "forgot" in result.lower()

        entry = await MemoryEntry.find_one(
            MemoryEntry.user_id == test_user.id,
            MemoryEntry.key == "to_delete",
        )
        assert entry is None

    async def test_forget_nonexistent(self, test_db, test_user):
        with pytest.raises(ToolError, match="No memory found"):
            await _forget_memory(str(test_user.id), "nonexistent_key")

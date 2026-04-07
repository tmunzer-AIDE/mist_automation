"""Tests for MemoryEntry and MemoryConsolidationLog Beanie models."""

from datetime import datetime

import pytest
from pymongo.errors import DuplicateKeyError

from app.modules.llm.models import MemoryConsolidationLog, MemoryEntry

# ---------------------------------------------------------------------------
# MemoryEntry
# ---------------------------------------------------------------------------


async def test_create_memory_entry(test_db, test_user):
    """MemoryEntry can be created and persisted with required fields."""
    entry = MemoryEntry(
        user_id=test_user.id,
        key="preferred_ap_model",
        value="AP45",
    )
    await entry.insert()

    found = await MemoryEntry.get(entry.id)
    assert found is not None
    assert found.user_id == test_user.id
    assert found.key == "preferred_ap_model"
    assert found.value == "AP45"
    assert isinstance(found.created_at, datetime)
    assert isinstance(found.updated_at, datetime)


async def test_unique_key_per_user(test_db, test_user):
    """Duplicate (user_id, key) raises DuplicateKeyError."""
    entry1 = MemoryEntry(user_id=test_user.id, key="site_name", value="HQ")
    await entry1.insert()

    entry2 = MemoryEntry(user_id=test_user.id, key="site_name", value="Branch")
    with pytest.raises(DuplicateKeyError):
        await entry2.insert()


async def test_default_category(test_db, test_user):
    """Default category is 'general'."""
    entry = MemoryEntry(user_id=test_user.id, key="test_default", value="val")
    await entry.insert()

    found = await MemoryEntry.get(entry.id)
    assert found.category == "general"


async def test_text_search(test_db, test_user):
    """MongoDB text index supports $text search on key+value."""
    await MemoryEntry(
        user_id=test_user.id, key="office_network", value="Main campus SSID corp-wifi"
    ).insert()
    await MemoryEntry(
        user_id=test_user.id, key="home_setup", value="Home lab with two APs"
    ).insert()

    # Text search for "campus" — compound text index requires user_id equality prefix
    results = await MemoryEntry.find(
        {"user_id": test_user.id, "$text": {"$search": "campus"}}
    ).to_list()
    assert len(results) == 1
    assert results[0].key == "office_network"


# ---------------------------------------------------------------------------
# MemoryConsolidationLog
# ---------------------------------------------------------------------------


async def test_create_consolidation_log(test_db, test_user):
    """MemoryConsolidationLog can be created with required fields."""
    log = MemoryConsolidationLog(
        user_id=test_user.id,
        entries_before=20,
        entries_after=15,
        actions=[{"action": "merge", "keys": ["k1", "k2"], "reason": "duplicate"}],
        llm_model="gpt-4o",
        llm_tokens_used=350,
    )
    await log.insert()

    found = await MemoryConsolidationLog.get(log.id)
    assert found is not None
    assert found.user_id == test_user.id
    assert found.entries_before == 20
    assert found.entries_after == 15
    assert len(found.actions) == 1
    assert found.actions[0]["action"] == "merge"
    assert found.llm_model == "gpt-4o"
    assert found.llm_tokens_used == 350
    assert isinstance(found.run_at, datetime)
    assert isinstance(found.created_at, datetime)

"""Tests for Redis client utility (challenge storage)."""

import pytest

from app.core.redis_client import WebAuthnChallengeStore


@pytest.fixture
def store():
    """Create a store with in-memory fallback."""
    return WebAuthnChallengeStore(redis=None)


@pytest.mark.asyncio
async def test_store_and_retrieve_challenge(store):
    """Can store a challenge and retrieve it."""
    await store.store_challenge("sess-1", {"challenge": "abc123", "user_id": "u1", "type": "registration"})
    data = await store.get_challenge("sess-1")
    assert data is not None
    assert data["challenge"] == "abc123"
    assert data["type"] == "registration"


@pytest.mark.asyncio
async def test_get_challenge_deletes_on_retrieve(store):
    """Challenge is deleted after retrieval (single-use)."""
    await store.store_challenge("sess-2", {"challenge": "xyz"})
    data = await store.get_challenge("sess-2")
    assert data is not None
    data2 = await store.get_challenge("sess-2")
    assert data2 is None


@pytest.mark.asyncio
async def test_get_nonexistent_challenge(store):
    """Missing challenge returns None."""
    data = await store.get_challenge("nonexistent")
    assert data is None


def test_generate_session_id():
    """Session ID is a 32-char hex string."""
    sid = WebAuthnChallengeStore.generate_session_id()
    assert isinstance(sid, str)
    assert len(sid) == 32

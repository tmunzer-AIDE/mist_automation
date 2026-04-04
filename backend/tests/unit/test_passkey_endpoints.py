"""Tests for passkey API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch

from app.core.redis_client import WebAuthnChallengeStore
from app.services.passkey_service import PasskeyService


def _make_passkey_service() -> PasskeyService:
    """Create a PasskeyService backed by the in-memory challenge store (no Redis)."""
    store = WebAuthnChallengeStore(redis=None)
    return PasskeyService(
        challenge_store=store,
        rp_id="localhost",
        rp_name="Mist Automation",
        expected_origin="http://localhost:4200",
    )


@pytest.mark.asyncio
async def test_passkey_register_begin(client):
    """POST /auth/passkey/register/begin returns challenge options."""
    with patch("app.api.v1.auth._get_passkey_service", new=AsyncMock(return_value=_make_passkey_service())):
        response = await client.post("/api/v1/auth/passkey/register/begin")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "options" in data
    assert "rp" in data["options"]
    assert "challenge" in data["options"]


@pytest.mark.asyncio
async def test_passkey_login_begin(client):
    """POST /auth/passkey/login/begin returns challenge options (unauthenticated)."""
    with patch("app.api.v1.auth._get_passkey_service", new=AsyncMock(return_value=_make_passkey_service())):
        response = await client.post("/api/v1/auth/passkey/login/begin")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "options" in data
    assert "challenge" in data["options"]


@pytest.mark.asyncio
async def test_passkey_list_empty(client):
    """GET /auth/passkeys returns empty list for new user."""
    response = await client.get("/api/v1/auth/passkeys")
    assert response.status_code == 200
    data = response.json()
    assert data["passkeys"] == []
    assert data["total"] == 0

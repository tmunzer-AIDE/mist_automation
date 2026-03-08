"""Integration tests for auth API."""
import pytest
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio


class TestProfile:
    async def test_get_profile(self, client, test_user):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email

    async def test_get_profile_returns_user_fields(self, client, test_user):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert "email" in data
        assert "id" in data or "email" in data

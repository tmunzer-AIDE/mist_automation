"""Unit tests for Personal Access Tokens (model, helpers, auth, endpoints)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.pat import PAT_PREFIX, generate_pat, hash_pat, is_pat_token
from app.models.personal_access_token import PersonalAccessToken
from app.modules.mcp_server.auth_middleware import MCPAuthMiddleware


@pytest.mark.unit
class TestPatHelpers:
    def test_generate_pat_format(self):
        plaintext, token_hash, token_prefix = generate_pat()
        assert plaintext.startswith(PAT_PREFIX)
        assert len(plaintext) > len(PAT_PREFIX) + 30
        assert token_hash == hash_pat(plaintext)
        assert token_prefix == plaintext[:13]
        assert len(token_hash) == 64  # sha256 hex digest

    def test_generate_pat_unique(self):
        a = generate_pat()[0]
        b = generate_pat()[0]
        assert a != b

    def test_hash_pat_deterministic(self):
        assert hash_pat("mist_pat_abc") == hash_pat("mist_pat_abc")
        assert hash_pat("mist_pat_abc") != hash_pat("mist_pat_def")

    def test_is_pat_token(self):
        assert is_pat_token("mist_pat_abcd1234")
        assert not is_pat_token("eyJhbGciOiJIUzI1NiJ9.jwt.token")
        assert not is_pat_token("")
        assert not is_pat_token("pat_abcd")


@pytest.mark.unit
class TestPersonalAccessTokenModel:
    @pytest.mark.asyncio
    async def test_roundtrip_lookup_by_hash(self, test_db, test_user):
        plaintext, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="test",
            token_hash=token_hash,
            token_prefix=token_prefix,
        )
        await pat.insert()

        found = await PersonalAccessToken.find_one(PersonalAccessToken.token_hash == token_hash)
        assert found is not None
        assert str(found.user_id) == str(test_user.id)
        assert found.name == "test"
        assert found.scopes == ["mcp"]

    @pytest.mark.asyncio
    async def test_is_usable_fresh(self, test_db, test_user):
        _, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="fresh",
            token_hash=token_hash,
            token_prefix=token_prefix,
        )
        assert pat.is_usable()
        assert not pat.is_expired()
        assert not pat.is_revoked()

    @pytest.mark.asyncio
    async def test_is_usable_revoked(self, test_db, test_user):
        _, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="revoked",
            token_hash=token_hash,
            token_prefix=token_prefix,
            revoked_at=datetime.now(timezone.utc),
        )
        assert not pat.is_usable()
        assert pat.is_revoked()

    @pytest.mark.asyncio
    async def test_is_usable_expired(self, test_db, test_user):
        _, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="expired",
            token_hash=token_hash,
            token_prefix=token_prefix,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert not pat.is_usable()
        assert pat.is_expired()

    @pytest.mark.asyncio
    async def test_is_usable_naive_expired_datetime(self, test_db, test_user):
        """Mongo may return naive datetimes; is_expired() must still work."""
        _, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="naive",
            token_hash=token_hash,
            token_prefix=token_prefix,
            expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None),
        )
        assert pat.is_expired()


@pytest.mark.unit
class TestMcpAuthDualPath:
    @pytest.mark.asyncio
    async def test_authenticate_pat_happy_path(self, test_db, test_user):
        plaintext, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="happy",
            token_hash=token_hash,
            token_prefix=token_prefix,
        )
        await pat.insert()

        user_id = await MCPAuthMiddleware._authenticate(plaintext)
        assert user_id == str(test_user.id)

    @pytest.mark.asyncio
    async def test_authenticate_pat_unknown_token(self, test_db, test_user):
        user_id = await MCPAuthMiddleware._authenticate("mist_pat_not_a_real_token")
        assert user_id is None

    @pytest.mark.asyncio
    async def test_authenticate_pat_revoked(self, test_db, test_user):
        plaintext, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="revoked",
            token_hash=token_hash,
            token_prefix=token_prefix,
            revoked_at=datetime.now(timezone.utc),
        )
        await pat.insert()

        user_id = await MCPAuthMiddleware._authenticate(plaintext)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_authenticate_pat_expired(self, test_db, test_user):
        plaintext, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="expired",
            token_hash=token_hash,
            token_prefix=token_prefix,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        await pat.insert()

        user_id = await MCPAuthMiddleware._authenticate(plaintext)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_authenticate_pat_inactive_user(self, test_db, test_user):
        plaintext, token_hash, token_prefix = generate_pat()
        pat = PersonalAccessToken(
            user_id=test_user.id,
            name="inactive",
            token_hash=token_hash,
            token_prefix=token_prefix,
        )
        await pat.insert()

        test_user.is_active = False
        await test_user.save()

        user_id = await MCPAuthMiddleware._authenticate(plaintext)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_authenticate_jwt_still_works(self, test_db, test_user, auth_token):
        from app.core.security import decode_token
        from app.models.session import UserSession

        payload = decode_token(auth_token)
        session = UserSession.create_session(
            user_id=test_user.id,
            token_jti=payload["jti"],
            ip_address="127.0.0.1",
        )
        await session.insert()

        user_id = await MCPAuthMiddleware._authenticate(auth_token)
        assert user_id == str(test_user.id)


@pytest.mark.unit
class TestPatEndpoints:
    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        r = await client.get("/api/v1/users/me/tokens")
        assert r.status_code == 200
        body = r.json()
        assert body["tokens"] == []
        assert body["total"] == 0
        assert body["max_per_user"] >= 1

    @pytest.mark.asyncio
    async def test_create_and_list(self, client):
        r = await client.post(
            "/api/v1/users/me/tokens",
            json={"name": "Claude Desktop"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["token"].startswith("mist_pat_")
        assert body["token_prefix"] == body["token"][:13]
        assert body["name"] == "Claude Desktop"
        assert body["revoked_at"] is None

        lst = await client.get("/api/v1/users/me/tokens")
        assert lst.status_code == 200
        tokens = lst.json()["tokens"]
        assert len(tokens) == 1
        assert tokens[0]["id"] == body["id"]
        assert "token" not in tokens[0]  # plaintext must never be listed

    @pytest.mark.asyncio
    async def test_create_rejects_past_expiry(self, client):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        r = await client.post(
            "/api/v1/users/me/tokens",
            json={"name": "stale", "expires_at": past},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_create_enforces_name(self, client):
        r = await client.post(
            "/api/v1/users/me/tokens",
            json={"name": "   "},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_revoke_hides_from_list(self, client):
        r = await client.post("/api/v1/users/me/tokens", json={"name": "to-revoke"})
        assert r.status_code == 201
        token_id = r.json()["id"]

        d = await client.delete(f"/api/v1/users/me/tokens/{token_id}")
        assert d.status_code == 204

        lst = await client.get("/api/v1/users/me/tokens")
        assert lst.json()["tokens"] == []

    @pytest.mark.asyncio
    async def test_revoke_unknown_404(self, client):
        # Valid ObjectId format, nonexistent
        r = await client.delete("/api/v1/users/me/tokens/507f1f77bcf86cd799439011")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_bad_id_400(self, client):
        r = await client.delete("/api/v1/users/me/tokens/not-an-id")
        assert r.status_code == 400

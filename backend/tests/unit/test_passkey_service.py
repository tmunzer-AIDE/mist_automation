"""Tests for PasskeyService."""

from unittest.mock import MagicMock

import pytest

from app.core.redis_client import WebAuthnChallengeStore
from app.models.user import WebAuthnCredential
from app.services.passkey_service import PasskeyService, PasskeyError, MAX_PASSKEYS


@pytest.fixture
def challenge_store():
    return WebAuthnChallengeStore(redis=None)


@pytest.fixture
def service(challenge_store):
    return PasskeyService(
        challenge_store=challenge_store,
        rp_id="localhost",
        rp_name="Test App",
        expected_origin="http://localhost:4200",
    )


def _make_mock_user(**overrides):
    """Create a mock User with sensible defaults. Beanie Documents can't be instantiated without DB."""
    user = MagicMock()
    user.id = overrides.get("id", "507f1f77bcf86cd799439011")
    user.email = overrides.get("email", "test@example.com")
    user.display_name.return_value = overrides.get("display_name", "Test User")
    user.webauthn_credentials = overrides.get("webauthn_credentials", [])
    return user


@pytest.mark.asyncio
async def test_generate_registration_options(service):
    """Registration begin returns session_id and options with correct RP info."""
    user = _make_mock_user()
    session_id, options = await service.generate_registration_options(user)
    assert isinstance(session_id, str)
    assert len(session_id) == 32
    assert options["rp"]["id"] == "localhost"
    assert options["rp"]["name"] == "Test App"
    assert options["user"]["name"] == "test@example.com"


@pytest.mark.asyncio
async def test_registration_excludes_existing_credentials(service):
    """Registration options exclude already-registered credential IDs."""
    cred = WebAuthnCredential(
        credential_id=b"\x01\x02\x03",
        public_key=b"\x04\x05\x06",
        sign_count=0,
        transports=["internal"],
        name="Existing Key",
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    user = _make_mock_user(webauthn_credentials=[cred])
    _, options = await service.generate_registration_options(user)
    assert len(options["excludeCredentials"]) == 1


@pytest.mark.asyncio
async def test_max_passkeys_enforced(service):
    """Cannot register more than MAX_PASSKEYS credentials."""
    creds = [
        WebAuthnCredential(
            credential_id=bytes([i]),
            public_key=bytes([i + 10]),
            sign_count=0,
            transports=["internal"],
            name=f"Key {i}",
            aaguid="00000000-0000-0000-0000-000000000000",
        )
        for i in range(MAX_PASSKEYS)
    ]
    user = _make_mock_user(webauthn_credentials=creds)
    with pytest.raises(PasskeyError, match="maximum"):
        await service.generate_registration_options(user)


@pytest.mark.asyncio
async def test_generate_authentication_options(service):
    """Authentication begin returns session_id and options."""
    session_id, options = await service.generate_authentication_options()
    assert isinstance(session_id, str)
    assert len(session_id) == 32
    assert "challenge" in options
    assert "rpId" in options


@pytest.mark.asyncio
async def test_verify_registration_expired_challenge(service):
    """Verify registration fails with expired/missing challenge."""
    user = _make_mock_user()
    with pytest.raises(PasskeyError, match="expired"):
        await service.verify_registration(user, "nonexistent-session", "{}", "My Key")


@pytest.mark.asyncio
async def test_verify_authentication_expired_challenge(service):
    """Verify authentication fails with expired/missing challenge."""
    cred = WebAuthnCredential(
        credential_id=b"\x01",
        public_key=b"\x02",
        sign_count=0,
    )
    with pytest.raises(PasskeyError, match="expired"):
        await service.verify_authentication("nonexistent", "{}", b"\x01", cred)

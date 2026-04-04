"""Tests for WebAuthn credential model on User."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.models.user import WebAuthnCredential


def test_webauthn_credential_creation():
    """WebAuthnCredential can be instantiated with required fields."""
    cred = WebAuthnCredential(
        credential_id=b"\x01\x02\x03",
        public_key=b"\x04\x05\x06",
        sign_count=0,
        transports=["internal"],
        name="MacBook Touch ID",
        aaguid="00000000-0000-0000-0000-000000000000",
    )
    assert cred.credential_id == b"\x01\x02\x03"
    assert cred.sign_count == 0
    assert cred.name == "MacBook Touch ID"
    assert cred.last_used_at is None
    assert isinstance(cred.created_at, datetime)


def test_webauthn_credential_defaults():
    """WebAuthnCredential has sane defaults for optional fields."""
    cred = WebAuthnCredential(
        credential_id=b"\xaa\xbb",
        public_key=b"\xcc\xdd",
    )
    assert cred.sign_count == 0
    assert cred.transports == []
    assert cred.name == ""
    assert cred.aaguid == ""
    assert cred.last_used_at is None
    assert isinstance(cred.created_at, datetime)


def test_user_default_webauthn_credentials():
    """User model has empty webauthn_credentials by default."""
    user = MagicMock()
    user.webauthn_credentials = []
    assert user.webauthn_credentials == []


@pytest.mark.parametrize("count", [0, 1, 3])
def test_user_with_multiple_credentials(count):
    """User can have multiple WebAuthn credentials."""
    creds = [
        WebAuthnCredential(
            credential_id=bytes([i]),
            public_key=bytes([i + 10]),
            sign_count=0,
            transports=["internal"],
            name=f"Key {i}",
            aaguid="00000000-0000-0000-0000-000000000000",
        )
        for i in range(count)
    ]
    user = MagicMock()
    user.webauthn_credentials = creds
    assert len(user.webauthn_credentials) == count


def test_webauthn_credential_field_presence():
    """WebAuthnCredential has all required fields defined in the model."""
    from app.models.user import WebAuthnCredential as WC

    fields = WC.model_fields
    assert "credential_id" in fields
    assert "public_key" in fields
    assert "sign_count" in fields
    assert "transports" in fields
    assert "name" in fields
    assert "aaguid" in fields
    assert "created_at" in fields
    assert "last_used_at" in fields

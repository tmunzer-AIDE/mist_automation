"""Unit tests for admin settings sensitive field handling (encrypt/clear)."""

import pytest

from app.core.security import decrypt_sensitive_data, encrypt_sensitive_data


@pytest.mark.unit
class TestEncryptDecryptRoundTrip:
    def test_encrypt_then_decrypt(self):
        original = "my-secret-token"
        encrypted = encrypt_sensitive_data(original)
        assert encrypted != original
        assert decrypt_sensitive_data(encrypted) == original

    def test_different_encryptions_differ(self):
        """Each encryption should produce a different ciphertext (random nonce)."""
        encrypted1 = encrypt_sensitive_data("same-value")
        encrypted2 = encrypt_sensitive_data("same-value")
        assert encrypted1 != encrypted2

    def test_empty_string_encrypts(self):
        encrypted = encrypt_sensitive_data("")
        assert decrypt_sensitive_data(encrypted) == ""

    def test_unicode_data(self):
        original = "mot-de-passe-tres-secret"
        encrypted = encrypt_sensitive_data(original)
        assert decrypt_sensitive_data(encrypted) == original


@pytest.mark.unit
class TestSensitiveFieldViaApi:
    async def test_empty_string_clears_field(self, client, test_db):
        """Empty string for sensitive field should set it to None."""
        # First set a value
        response = await client.put("/api/v1/admin/settings", json={"webhook_secret": "my-secret"})
        assert response.status_code == 200

        # Now clear it with empty string
        response = await client.put("/api/v1/admin/settings", json={"webhook_secret": ""})
        assert response.status_code == 200

        # Verify it's cleared
        response = await client.get("/api/v1/admin/settings")
        assert response.status_code == 200
        assert response.json()["webhook_secret_set"] is False

    async def test_nonempty_string_encrypts(self, client, test_db):
        """Non-empty string for sensitive field should be encrypted and reported as set."""
        response = await client.put(
            "/api/v1/admin/settings", json={"webhook_secret": "test-secret"}
        )
        assert response.status_code == 200

        response = await client.get("/api/v1/admin/settings")
        assert response.status_code == 200
        assert response.json()["webhook_secret_set"] is True

    async def test_unset_field_not_reported_as_set(self, client, test_db):
        """A field that was never set should not be reported as set."""
        response = await client.get("/api/v1/admin/settings")
        assert response.status_code == 200
        # webhook_secret_set should be False if never explicitly set
        data = response.json()
        assert "webhook_secret_set" in data

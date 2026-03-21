"""Extended unit tests for security utilities — encryption, refresh tokens, password policy, backup codes."""

import base64

import pytest
from unittest.mock import patch, MagicMock

from app.core.security import (
    create_refresh_token,
    decrypt_sensitive_data,
    encrypt_sensitive_data,
    generate_backup_codes,
    hash_backup_code,
    validate_password_strength,
    verify_backup_code,
)


@pytest.mark.unit
class TestEncryptDecryptRoundTrip:
    """Tests for encrypt_sensitive_data / decrypt_sensitive_data."""

    def test_round_trip_with_default_key(self):
        plaintext = "my-secret-api-token-12345"
        encrypted = encrypt_sensitive_data(plaintext)
        assert encrypted != plaintext
        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == plaintext

    def test_round_trip_with_custom_key(self):
        plaintext = "another-secret-value"
        custom_key = "my-custom-encryption-key-that-is-long-enough"
        encrypted = encrypt_sensitive_data(plaintext, key=custom_key)
        decrypted = decrypt_sensitive_data(encrypted, key=custom_key)
        assert decrypted == plaintext

    def test_custom_key_cannot_decrypt_with_default_key(self):
        plaintext = "cross-key-test"
        custom_key = "custom-key-for-encryption"
        encrypted = encrypt_sensitive_data(plaintext, key=custom_key)
        with pytest.raises(Exception):
            decrypt_sensitive_data(encrypted)  # uses default key, should fail

    def test_default_key_cannot_decrypt_with_wrong_custom_key(self):
        plaintext = "another-cross-key-test"
        encrypted = encrypt_sensitive_data(plaintext)  # default key
        with pytest.raises(Exception):
            decrypt_sensitive_data(encrypted, key="wrong-key")

    def test_different_encryptions_produce_different_ciphertexts(self):
        """Each encryption uses a random salt and nonce, so ciphertexts should differ."""
        plaintext = "same-data"
        enc1 = encrypt_sensitive_data(plaintext)
        enc2 = encrypt_sensitive_data(plaintext)
        assert enc1 != enc2

    def test_round_trip_empty_string(self):
        plaintext = ""
        encrypted = encrypt_sensitive_data(plaintext)
        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == plaintext

    def test_round_trip_unicode(self):
        plaintext = "unicode-test-data-with-accents-and-symbols"
        encrypted = encrypt_sensitive_data(plaintext)
        decrypted = decrypt_sensitive_data(encrypted)
        assert decrypted == plaintext


@pytest.mark.unit
class TestDecryptErrors:
    """Tests for decrypt_sensitive_data error handling."""

    def test_truncated_data_raises_value_error(self):
        """Data shorter than 44 bytes (16 salt + 12 nonce + 16 GCM tag) should fail."""
        # Create base64-encoded data that decodes to < 44 bytes
        short_raw = b"x" * 43
        short_b64 = base64.urlsafe_b64encode(short_raw).decode()
        with pytest.raises(ValueError, match="corrupted or truncated"):
            decrypt_sensitive_data(short_b64)

    def test_very_short_data_raises_value_error(self):
        short_b64 = base64.urlsafe_b64encode(b"short").decode()
        with pytest.raises(ValueError, match="corrupted or truncated"):
            decrypt_sensitive_data(short_b64)

    def test_corrupted_ciphertext_raises(self):
        """Valid-length but random data should fail decryption (GCM auth tag mismatch)."""
        # 45+ bytes of random-looking data, but not a valid ciphertext
        garbage_raw = b"A" * 60
        garbage_b64 = base64.urlsafe_b64encode(garbage_raw).decode()
        with pytest.raises(Exception):
            decrypt_sensitive_data(garbage_b64)

    def test_invalid_base64_raises(self):
        """Non-base64 strings should raise."""
        with pytest.raises(Exception):
            decrypt_sensitive_data("not-valid-base64!!!")


@pytest.mark.unit
class TestCreateRefreshToken:
    """Tests for create_refresh_token."""

    def test_returns_string(self):
        token = create_refresh_token({"sub": "user-id-123"})
        assert isinstance(token, str)

    def test_does_not_return_tuple(self):
        result = create_refresh_token({"sub": "user-id-456"})
        assert not isinstance(result, tuple)

    def test_token_contains_refresh_type(self):
        from app.core.security import decode_token

        token = create_refresh_token({"sub": "user-id-789"})
        payload = decode_token(token)
        assert payload is not None
        assert payload.get("type") == "refresh"

    def test_token_preserves_subject(self):
        from app.core.security import decode_token

        token = create_refresh_token({"sub": "my-user"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "my-user"


@pytest.mark.unit
class TestValidatePasswordStrengthExplicitPolicy:
    """Tests for validate_password_strength with explicit policy parameters."""

    def test_min_length_enforced(self):
        valid, error = validate_password_strength("Ab1!", min_length=10)
        assert valid is False
        assert "at least 10 characters" in error

    def test_min_length_exact_boundary_passes(self):
        # Exactly 5 chars, min_length=5, disable all requirements
        valid, _ = validate_password_strength(
            "abcde",
            min_length=5,
            require_uppercase=False,
            require_lowercase=False,
            require_digits=False,
            require_special_chars=False,
        )
        assert valid is True

    def test_require_uppercase_flag(self):
        valid, error = validate_password_strength(
            "alllowercase123!",
            min_length=1,
            require_uppercase=True,
            require_lowercase=False,
            require_digits=False,
            require_special_chars=False,
        )
        assert valid is False
        assert "uppercase" in error

    def test_require_uppercase_disabled(self):
        valid, _ = validate_password_strength(
            "alllowercase123",
            min_length=1,
            require_uppercase=False,
            require_lowercase=False,
            require_digits=False,
            require_special_chars=False,
        )
        assert valid is True

    def test_require_lowercase_flag(self):
        valid, error = validate_password_strength(
            "ALLUPPERCASE123!",
            min_length=1,
            require_uppercase=False,
            require_lowercase=True,
            require_digits=False,
            require_special_chars=False,
        )
        assert valid is False
        assert "lowercase" in error

    def test_require_lowercase_disabled(self):
        valid, _ = validate_password_strength(
            "ALLUPPERCASE123",
            min_length=1,
            require_uppercase=False,
            require_lowercase=False,
            require_digits=False,
            require_special_chars=False,
        )
        assert valid is True

    def test_require_digits_flag(self):
        valid, error = validate_password_strength(
            "NoDigitsHere!",
            min_length=1,
            require_uppercase=False,
            require_lowercase=False,
            require_digits=True,
            require_special_chars=False,
        )
        assert valid is False
        assert "digit" in error

    def test_require_digits_disabled(self):
        valid, _ = validate_password_strength(
            "NoDigitsHere",
            min_length=1,
            require_uppercase=False,
            require_lowercase=False,
            require_digits=False,
            require_special_chars=False,
        )
        assert valid is True

    def test_require_special_chars_flag(self):
        valid, error = validate_password_strength(
            "NoSpecialChars123",
            min_length=1,
            require_uppercase=False,
            require_lowercase=False,
            require_digits=False,
            require_special_chars=True,
        )
        assert valid is False
        assert "special character" in error

    def test_require_special_chars_disabled(self):
        valid, _ = validate_password_strength(
            "NoSpecialChars123",
            min_length=1,
            require_uppercase=False,
            require_lowercase=False,
            require_digits=False,
            require_special_chars=False,
        )
        assert valid is True

    def test_all_requirements_pass(self):
        valid, error = validate_password_strength(
            "MyStr0ng!Pass",
            min_length=8,
            require_uppercase=True,
            require_lowercase=True,
            require_digits=True,
            require_special_chars=True,
        )
        assert valid is True
        assert error is None

    def test_fallback_to_settings_defaults(self):
        """When no explicit params are passed, settings defaults are used."""
        mock_settings = MagicMock()
        mock_settings.min_password_length = 4
        mock_settings.require_uppercase = False
        mock_settings.require_lowercase = False
        mock_settings.require_digits = False
        mock_settings.require_special_chars = False

        with patch("app.core.security.settings", mock_settings):
            valid, error = validate_password_strength("abcd")
            assert valid is True
            assert error is None

    def test_fallback_to_settings_defaults_fails(self):
        """When no explicit params are passed and password doesn't meet defaults."""
        mock_settings = MagicMock()
        mock_settings.min_password_length = 20
        mock_settings.require_uppercase = False
        mock_settings.require_lowercase = False
        mock_settings.require_digits = False
        mock_settings.require_special_chars = False

        with patch("app.core.security.settings", mock_settings):
            valid, error = validate_password_strength("short")
            assert valid is False
            assert "at least 20 characters" in error


@pytest.mark.unit
class TestGenerateBackupCodes:
    """Tests for generate_backup_codes."""

    def test_default_count(self):
        codes = generate_backup_codes()
        assert len(codes) == 10

    def test_custom_count(self):
        codes = generate_backup_codes(count=5)
        assert len(codes) == 5

    def test_zero_count(self):
        codes = generate_backup_codes(count=0)
        assert len(codes) == 0

    def test_format_xxxx_xxxx(self):
        codes = generate_backup_codes(count=20)
        for code in codes:
            parts = code.split("-")
            assert len(parts) == 2, f"Code '{code}' should have exactly one hyphen"
            assert len(parts[0]) == 4, f"First part of '{code}' should be 4 chars"
            assert len(parts[1]) == 4, f"Second part of '{code}' should be 4 chars"
            # Characters should be uppercase alphanumeric
            for part in parts:
                assert part.isalnum(), f"Part '{part}' should be alphanumeric"
                assert part == part.upper(), f"Part '{part}' should be uppercase"

    def test_uniqueness(self):
        codes = generate_backup_codes(count=50)
        assert len(codes) == len(set(codes)), "All generated codes should be unique"


@pytest.mark.unit
class TestBackupCodeHashAndVerify:
    """Tests for hash_backup_code / verify_backup_code round-trip."""

    def test_round_trip(self):
        codes = generate_backup_codes(count=3)
        for code in codes:
            hashed = hash_backup_code(code)
            assert verify_backup_code(code, hashed) is True

    def test_wrong_code_fails(self):
        code = generate_backup_codes(count=1)[0]
        hashed = hash_backup_code(code)
        assert verify_backup_code("XXXX-YYYY", hashed) is False

    def test_hyphen_stripping(self):
        """Verifying with or without hyphens should work since hyphens are stripped."""
        code = generate_backup_codes(count=1)[0]
        hashed = hash_backup_code(code)
        # Verify with the code without hyphens
        code_no_hyphen = code.replace("-", "")
        assert verify_backup_code(code_no_hyphen, hashed) is True

    def test_hash_is_not_plaintext(self):
        code = generate_backup_codes(count=1)[0]
        hashed = hash_backup_code(code)
        assert hashed != code
        assert hashed != code.replace("-", "")

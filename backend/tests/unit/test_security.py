"""Unit tests for security utilities."""
import pytest
from app.core.security import (
    hash_password, verify_password, create_access_token, decode_token,
    validate_password_strength
)


class TestPasswordHashing:
    def test_hash_and_verify_correct_password(self):
        hashed = hash_password("MySecurePass123!")
        assert verify_password("MySecurePass123!", hashed)

    def test_verify_wrong_password_fails(self):
        hashed = hash_password("MySecurePass123!")
        assert not verify_password("WrongPassword", hashed)

    def test_different_hashes_for_same_password(self):
        hashed1 = hash_password("MySecurePass123!")
        hashed2 = hash_password("MySecurePass123!")
        # bcrypt generates different salts each time
        assert hashed1 != hashed2


class TestJwtTokens:
    def test_create_and_decode_valid_token(self):
        token, _ = create_access_token({"sub": "user123", "email": "test@example.com"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user123"

    def test_decode_invalid_token_returns_none(self):
        result = decode_token("invalid.token.here")
        assert result is None

    def test_token_includes_jti(self):
        token, jti = create_access_token({"sub": "user123"})
        assert jti is not None
        payload = decode_token(token)
        assert payload["jti"] == jti

    def test_token_includes_expiry(self):
        token, _ = create_access_token({"sub": "user123"})
        payload = decode_token(token)
        assert "exp" in payload


class TestPasswordStrength:
    def test_strong_password_passes(self):
        valid, error = validate_password_strength("MyStr0ngPass")
        assert valid is True
        assert error is None

    def test_weak_password_too_short_fails(self):
        valid, error = validate_password_strength("weak")
        assert valid is False
        assert error is not None

    def test_password_missing_uppercase_fails(self):
        valid, error = validate_password_strength("mysecurepass123")
        assert valid is False
        assert error is not None

    def test_password_missing_lowercase_fails(self):
        valid, error = validate_password_strength("MYSECUREPASS123")
        assert valid is False
        assert error is not None

    def test_password_missing_digit_fails(self):
        valid, error = validate_password_strength("MySecurePassword")
        assert valid is False
        assert error is not None

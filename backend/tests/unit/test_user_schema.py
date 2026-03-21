"""
Unit tests for user schemas and helpers.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate, user_to_response


@pytest.mark.unit
class TestUserToResponse:
    """Test user_to_response helper function."""

    def test_maps_all_fields_correctly(self):
        now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        user = MagicMock()
        user.id = "abc123objectid"
        user.email = "alice@example.com"
        user.first_name = "Alice"
        user.last_name = "Smith"
        user.roles = ["admin", "automation"]
        user.timezone = "America/New_York"
        user.is_active = True
        user.totp_enabled = False
        user.created_at = now
        user.updated_at = now
        user.last_login = None

        response = user_to_response(user)

        assert response.id == "abc123objectid"
        assert response.email == "alice@example.com"
        assert response.first_name == "Alice"
        assert response.last_name == "Smith"
        assert response.roles == ["admin", "automation"]
        assert response.timezone == "America/New_York"
        assert response.is_active is True
        assert response.totp_enabled is False
        assert response.created_at == now
        assert response.updated_at == now
        assert response.last_login is None

    def test_id_converted_to_string(self):
        now = datetime.now(timezone.utc)
        user = MagicMock()
        user.id = 12345
        user.email = "test@example.com"
        user.first_name = None
        user.last_name = None
        user.roles = []
        user.timezone = "UTC"
        user.is_active = True
        user.totp_enabled = False
        user.created_at = now
        user.updated_at = now
        user.last_login = None

        response = user_to_response(user)

        assert response.id == "12345"
        assert isinstance(response.id, str)


@pytest.mark.unit
class TestUserCreateRoleValidation:
    """Test UserCreate role validation."""

    def test_valid_roles_pass(self):
        user = UserCreate(
            email="test@example.com",
            password="secret",
            roles=["admin", "automation"],
        )
        assert user.roles == ["admin", "automation"]

    def test_invalid_role_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="test@example.com",
                password="secret",
                roles=["superadmin"],
            )
        assert "Invalid roles" in str(exc_info.value)

    def test_empty_roles_pass(self):
        user = UserCreate(
            email="test@example.com",
            password="secret",
            roles=[],
        )
        assert user.roles == []

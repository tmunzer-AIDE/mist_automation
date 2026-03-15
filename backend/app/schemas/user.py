"""
User management schemas.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

_ALLOWED_ROLES = {"admin", "automation", "backup", "reports"}


class UserCreate(BaseModel):
    """User creation schema."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password", min_length=1)
    roles: list[str] = Field(default_factory=list, description="User roles")
    timezone: str = Field(default="UTC", description="User timezone")

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: list[str]) -> list[str]:
        invalid = set(v) - _ALLOWED_ROLES
        if invalid:
            raise ValueError(f"Invalid roles: {invalid}. Allowed: {_ALLOWED_ROLES}")
        return v


class UserUpdate(BaseModel):
    """User update schema."""

    email: EmailStr | None = Field(None, description="User email address")
    roles: list[str] | None = Field(None, description="User roles")
    timezone: str | None = Field(None, description="User timezone")
    is_active: bool | None = Field(None, description="Whether user is active")

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            invalid = set(v) - _ALLOWED_ROLES
            if invalid:
                raise ValueError(f"Invalid roles: {invalid}. Allowed: {_ALLOWED_ROLES}")
        return v


class UserResponse(BaseModel):
    """User response schema."""

    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    roles: list[str] = Field(..., description="User roles")
    timezone: str = Field(..., description="User timezone")
    is_active: bool = Field(..., description="Whether user is active")
    totp_enabled: bool = Field(..., description="Whether 2FA is enabled")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    last_login: datetime | None = Field(None, description="Last login timestamp")

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """User list response schema."""

    users: list[UserResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total number of users")

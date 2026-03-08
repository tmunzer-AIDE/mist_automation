"""
User management schemas.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """User creation schema."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password", min_length=8)
    roles: list[str] = Field(default_factory=list, description="User roles")
    timezone: str = Field(default="UTC", description="User timezone")


class UserUpdate(BaseModel):
    """User update schema."""

    email: EmailStr | None = Field(None, description="User email address")
    roles: list[str] | None = Field(None, description="User roles")
    timezone: str | None = Field(None, description="User timezone")
    is_active: bool | None = Field(None, description="Whether user is active")


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

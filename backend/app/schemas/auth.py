"""
Authentication request/response schemas.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password", min_length=8)
    remember_me: bool = Field(default=False, description="Keep user logged in for longer")


class TokenResponse(BaseModel):
    """Token response schema."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")


class UserResponse(BaseModel):
    """User response schema."""

    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    roles: list[str] = Field(..., description="User roles")
    timezone: str = Field(..., description="User timezone")
    is_active: bool = Field(..., description="Whether user is active")
    totp_enabled: bool = Field(..., description="Whether 2FA is enabled")
    created_at: datetime = Field(..., description="Account creation timestamp")
    last_login: datetime | None = Field(None, description="Last login timestamp")

    class Config:
        from_attributes = True

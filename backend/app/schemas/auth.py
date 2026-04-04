"""
Authentication request/response schemas.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password", min_length=1)
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
    first_name: str | None = Field(None, description="User first name")
    last_name: str | None = Field(None, description="User last name")
    roles: list[str] = Field(..., description="User roles")
    timezone: str = Field(..., description="User timezone")
    is_active: bool = Field(..., description="Whether user is active")
    totp_enabled: bool = Field(..., description="Whether 2FA is enabled")
    has_passkeys: bool = Field(default=False, description="Whether user has registered passkeys")
    created_at: datetime = Field(..., description="Account creation timestamp")
    last_login: datetime | None = Field(None, description="Last login timestamp")

    class Config:
        from_attributes = True


class OnboardRequest(BaseModel):
    """Onboarding request schema for first admin user."""

    email: EmailStr = Field(..., description="Admin email address")
    password: str = Field(..., description="Admin password", min_length=1)
    first_name: str | None = Field(None, description="Admin first name")
    last_name: str | None = Field(None, description="Admin last name")


class ChangePasswordRequest(BaseModel):
    """Change password request schema."""

    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., description="New password", min_length=1)


class UpdateProfileRequest(BaseModel):
    """Update profile request schema."""

    first_name: str | None = Field(None, description="User first name")
    last_name: str | None = Field(None, description="User last name")
    timezone: str | None = Field(None, description="User timezone (IANA)")


class SessionResponse(BaseModel):
    """Session response schema."""

    id: str
    user_id: str
    device_info: dict
    trusted_device: bool
    created_at: datetime
    last_activity: datetime
    expires_at: datetime
    is_current: bool = False


class SessionListResponse(BaseModel):
    """Session list response schema."""

    sessions: list[SessionResponse]
    total: int


class PasskeyRegisterBeginResponse(BaseModel):
    """Response from passkey registration begin."""

    session_id: str = Field(..., description="Challenge session ID")
    options: dict = Field(..., description="PublicKeyCredentialCreationOptions")


class PasskeyRegisterCompleteRequest(BaseModel):
    """Request to complete passkey registration."""

    session_id: str = Field(..., description="Challenge session ID from begin step")
    credential: str = Field(..., description="JSON-encoded attestation response from browser")
    name: str = Field("Passkey", description="User-friendly name for this passkey", max_length=100)


class PasskeyLoginBeginResponse(BaseModel):
    """Response from passkey login begin."""

    session_id: str = Field(..., description="Challenge session ID")
    options: dict = Field(..., description="PublicKeyCredentialRequestOptions")


class PasskeyLoginCompleteRequest(BaseModel):
    """Request to complete passkey login."""

    session_id: str = Field(..., description="Challenge session ID from begin step")
    credential: str = Field(..., description="JSON-encoded assertion response from browser")


class PasskeyResponse(BaseModel):
    """A registered passkey (public info only)."""

    id: str = Field(..., description="Base64url credential ID")
    name: str = Field(..., description="User-given name")
    created_at: datetime = Field(..., description="When the passkey was registered")
    last_used_at: datetime | None = Field(None, description="Last successful authentication")
    transports: list[str] = Field(default_factory=list, description="Transport hints")


class PasskeyListResponse(BaseModel):
    """List of user's passkeys."""

    passkeys: list[PasskeyResponse]
    total: int


class PasskeyDeleteRequest(BaseModel):
    """Request to delete a passkey (requires password re-auth)."""

    password: str = Field(..., description="Current password for re-authentication")

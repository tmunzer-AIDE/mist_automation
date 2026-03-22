"""
User session model for JWT token tracking and session management.
"""

from datetime import datetime, timedelta, timezone

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from app.config import settings


class DeviceInfo(BaseModel):
    """Device information for session tracking."""

    browser: str | None = Field(default=None, description="Browser name and version")
    os: str | None = Field(default=None, description="Operating system")
    ip_address: str = Field(..., description="IP address of the client")
    user_agent: str | None = Field(default=None, description="Full user agent string")


class UserSession(Document):
    """User session model for tracking active JWT tokens."""

    user_id: PydanticObjectId = Field(..., description="Reference to user")
    token_jti: str = Field(..., description="JWT ID for token revocation")

    # Device and location info
    device_info: DeviceInfo = Field(..., description="Device information")

    # Trust and security
    trusted_device: bool = Field(default=False, description="Whether this device is trusted for 30 days")

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(..., description="Session expiration time")

    class Settings:
        name = "user_sessions"
        indexes = [
            "user_id",
            "token_jti",
            "last_activity",
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]

    @classmethod
    def create_session(
        cls,
        user_id: PydanticObjectId,
        token_jti: str,
        ip_address: str,
        user_agent: str | None = None,
        browser: str | None = None,
        os: str | None = None,
        trusted_device: bool = False,
        expires_delta: timedelta | None = None,
    ) -> "UserSession":
        """Create a new user session."""
        device_info = DeviceInfo(
            browser=browser,
            os=os,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        expires_at = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=settings.access_token_expire_hours))

        return cls(
            user_id=user_id,
            token_jti=token_jti,
            device_info=device_info,
            trusted_device=trusted_device,
            expires_at=expires_at,
        )

    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)

    def is_expired(self) -> bool:
        """Check if session has expired."""
        now = datetime.now(timezone.utc)
        expires = self.expires_at
        # MongoDB may return naive datetimes; make comparison safe
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now > expires

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "507f1f77bcf86cd799439011",
                "token_jti": "abc123xyz",
                "device_info": {
                    "browser": "Chrome 120.0",
                    "os": "macOS 14.0",
                    "ip_address": "192.168.1.1",
                },
                "trusted_device": False,
            }
        }

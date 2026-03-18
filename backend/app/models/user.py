"""
User model for authentication and authorization.
"""

from datetime import datetime, timezone

from beanie import Document
from pydantic import EmailStr, Field

from app.models.mixins import TimestampMixin


class User(TimestampMixin, Document):
    """User model with authentication and authorization data."""
    
    email: EmailStr = Field(..., description="User email address")
    password_hash: str = Field(..., description="Hashed password")
    roles: list[str] = Field(default_factory=list, description="User roles: admin, automation, backup, reports")

    # Profile information
    first_name: str | None = Field(default=None, description="User first name")
    last_name: str | None = Field(default=None, description="User last name")
    timezone: str = Field(default="UTC", description="User timezone for cron schedules")
    is_active: bool = Field(default=True, description="Whether the user account is active")
    
    # Two-Factor Authentication
    totp_secret: str | None = Field(default=None, description="TOTP secret for 2FA (encrypted)")
    totp_enabled: bool = Field(default=False, description="Whether 2FA is enabled")
    backup_codes: list[str] = Field(default_factory=list, description="Hashed backup codes for 2FA recovery")

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: datetime | None = Field(default=None, description="Last successful login timestamp")
    
    class Settings:
        name = "users"
        indexes = [
            "email",
            "is_active",
        ]
    
    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles
    
    def has_any_role(self, *roles: str) -> bool:
        """Check if user has any of the specified roles."""
        return any(role in self.roles for role in roles)
    
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.has_role("admin")
    
    def can_manage_workflows(self) -> bool:
        """Check if user can manage workflows."""
        return self.has_any_role("admin", "automation")
    
    def can_manage_backups(self) -> bool:
        """Check if user can manage backups."""
        return self.has_any_role("admin", "backup")

    def can_manage_reports(self) -> bool:
        """Check if user can manage reports."""
        return self.has_any_role("admin", "reports")

    def display_name(self) -> str:
        """Return a display-friendly name, falling back to the email local part."""
        if self.first_name:
            parts = [self.first_name]
            if self.last_name:
                parts.append(self.last_name)
            return " ".join(parts)
        return self.email.split("@")[0]

    def update_last_login(self):
        """Update last login timestamp."""
        self.last_login = datetime.now(timezone.utc)
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "admin@example.com",
                "roles": ["admin", "automation", "backup", "reports"],
                "timezone": "America/Los_Angeles",
                "is_active": True,
                "totp_enabled": False,
            }
        }

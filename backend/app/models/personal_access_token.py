"""
Personal Access Token model.

Long-lived bearer tokens used by external MCP clients (Claude Desktop, VS Code,
Cursor, ...) to authenticate against the MCP server without a browser session.
Only the SHA-256 hash of the token is stored — plaintext is shown to the user
once on creation.
"""

from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.models.mixins import TimestampMixin


class PersonalAccessToken(TimestampMixin, Document):
    """Personal Access Token for MCP client authentication."""

    user_id: PydanticObjectId = Field(..., description="Owning user")
    name: str = Field(..., description="Human-readable label, e.g. 'Claude Desktop'")

    token_hash: str = Field(..., description="SHA-256 hex digest of the plaintext token")
    token_prefix: str = Field(..., description="First 13 chars of the plaintext for UI display")

    scopes: list[str] = Field(
        default_factory=lambda: ["mcp"],
        description="Scopes granted (currently informational — every token is full-access)",
    )

    expires_at: datetime | None = Field(default=None, description="Optional expiration")
    last_used_at: datetime | None = Field(default=None, description="Last successful auth")
    revoked_at: datetime | None = Field(default=None, description="Revocation timestamp")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "personal_access_tokens"
        indexes = [
            IndexModel([("token_hash", ASCENDING)], unique=True),
            "user_id",
            "revoked_at",
        ]

    def is_expired(self) -> bool:
        """Whether the token has passed its expiration time."""
        if self.expires_at is None:
            return False
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires

    def is_revoked(self) -> bool:
        """Whether the token has been revoked."""
        return self.revoked_at is not None

    def is_usable(self) -> bool:
        """Whether the token can currently authenticate."""
        return not self.is_revoked() and not self.is_expired()

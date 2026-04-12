"""
Personal Access Token schemas.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class PATCreateRequest(BaseModel):
    """Request body for creating a new PAT."""

    name: str = Field(..., min_length=1, max_length=100, description="Human-readable label")
    expires_at: datetime | None = Field(default=None, description="Optional expiration time (UTC). Omit for no expiry.")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class PATResponse(BaseModel):
    """PAT metadata (no plaintext)."""

    id: str
    name: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


class PATCreateResponse(PATResponse):
    """Response for a newly created PAT — includes the plaintext token ONCE."""

    token: str = Field(..., description="The plaintext token. Shown exactly once; store securely.")


class PATListResponse(BaseModel):
    """List of PATs owned by the caller."""

    tokens: list[PATResponse]
    total: int
    max_per_user: int

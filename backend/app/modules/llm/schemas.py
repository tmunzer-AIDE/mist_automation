"""
LLM request/response schemas.
"""

from pydantic import BaseModel, Field

# ── Backup Summarization ─────────────────────────────────────────────────────


class SummarizeDiffRequest(BaseModel):
    """Request to summarize changes between two backup object versions."""

    version_id_1: str = Field(..., description="Older version document ID")
    version_id_2: str = Field(..., description="Newer version document ID")
    thread_id: str | None = Field(None, description="Existing conversation thread ID for follow-up")


class SummaryResponse(BaseModel):
    """Response from an LLM summarization request."""

    summary: str
    thread_id: str
    usage: dict = Field(default_factory=dict)


# ── Conversation Follow-Up ───────────────────────────────────────────────────


class FollowUpRequest(BaseModel):
    """Request to continue a conversation thread."""

    message: str = Field(..., min_length=1, max_length=4000, description="User follow-up message")


class ChatResponse(BaseModel):
    """Response from a follow-up conversation message."""

    reply: str
    thread_id: str
    usage: dict = Field(default_factory=dict)

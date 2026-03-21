"""
LLM module models: usage tracking and conversation threads.
"""

from datetime import datetime, timezone

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel


class LLMUsageLog(Document):
    """Tracks LLM API usage for cost monitoring."""

    user_id: PydanticObjectId = Field(..., description="User who made the request")
    feature: str = Field(..., description="Feature that triggered the call (backup_summary, workflow_assist, etc.)")
    model: str = Field(..., description="LLM model used")
    provider: str = Field(..., description="LLM provider (openai, anthropic, ollama, etc.)")
    prompt_tokens: int = Field(default=0, description="Input tokens consumed")
    completion_tokens: int = Field(default=0, description="Output tokens generated")
    total_tokens: int = Field(default=0, description="Total tokens consumed")
    duration_ms: int | None = Field(default=None, description="Request duration in milliseconds")
    timestamp: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "llm_usage_logs"
        indexes = [
            IndexModel([("user_id", 1), ("timestamp", -1)]),
            "feature",
            IndexModel([("timestamp", 1)], expireAfterSeconds=365 * 24 * 3600),
        ]


class ConversationMessage(BaseModel):
    """A single message in a conversation thread."""

    role: str = Field(..., description="Message role: system, user, or assistant")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationThread(Document):
    """Stores multi-turn LLM conversation history."""

    user_id: PydanticObjectId = Field(..., description="User who owns this thread")
    feature: str = Field(..., description="Feature context (backup_summary, workflow_assist, etc.)")
    context_ref: str | None = Field(default=None, description="Reference to related object (backup_id, workflow_id)")
    messages: list[ConversationMessage] = Field(default_factory=list, description="Conversation messages")
    is_archived: bool = Field(default=False, description="Whether the thread is archived")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "llm_conversations"
        indexes = [
            [("user_id", 1), ("created_at", -1)],
            "feature",
            IndexModel([("updated_at", 1)], expireAfterSeconds=90 * 24 * 3600),
        ]

    def add_message(self, role: str, content: str) -> None:
        """Append a message and update timestamp."""
        self.messages.append(ConversationMessage(role=role, content=content))
        self.updated_at = datetime.now(timezone.utc)

    def get_messages_for_llm(self, max_turns: int = 20) -> list[dict[str, str]]:
        """Return messages for the LLM, capped with a sliding window.

        Keeps all system messages + the last ``max_turns`` non-system messages
        to avoid exceeding the model's context window on long threads.
        """
        system = [{"role": m.role, "content": m.content} for m in self.messages if m.role == "system"]
        non_system = [{"role": m.role, "content": m.content} for m in self.messages if m.role != "system"]
        return system + non_system[-max_turns:]

    def to_llm_messages(self, max_turns: int = 20):
        """Return messages as LLMMessage objects ready for the LLM service."""
        from app.modules.llm.services.llm_service import LLMMessage

        return [LLMMessage(role=m["role"], content=m["content"]) for m in self.get_messages_for_llm(max_turns)]

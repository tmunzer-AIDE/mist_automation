"""
LLM module models: provider configs, usage tracking, and conversation threads.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from app.models.mixins import TimestampMixin


class LLMConfig(TimestampMixin, Document):
    """A named LLM provider configuration."""

    name: str = Field(..., description="Display name (e.g., 'GPT-4o Cloud', 'Local Qwen')")
    provider: str = Field(..., description="Provider: openai, anthropic, ollama, lm_studio, azure_openai, bedrock, vertex")
    api_key: str | None = Field(default=None, description="Encrypted API key")
    model: str | None = Field(default=None, description="Model name")
    base_url: str | None = Field(default=None, description="Custom API base URL")
    temperature: float = Field(default=0.3, description="Temperature (0.0-2.0)")
    max_tokens_per_request: int = Field(default=4096, description="Max output tokens")
    is_default: bool = Field(default=False, description="Default config for UI features")
    enabled: bool = Field(default=True, description="Whether this config is active")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "llm_configs"
        indexes = ["name", "is_default"]


class MCPConfig(TimestampMixin, Document):
    """A named MCP server configuration."""

    name: str = Field(..., description="Display name (e.g., 'Mist MCP', 'Custom Tools')")
    url: str = Field(..., description="Streamable HTTP endpoint URL")
    headers: str | None = Field(default=None, description="Encrypted JSON headers (contains auth tokens)")
    ssl_verify: bool = Field(default=True, description="Verify SSL certificates")
    enabled: bool = Field(default=True, description="Whether this config is active")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "mcp_configs"
        indexes = ["name"]


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
    metadata: dict | None = Field(default=None, description="Optional metadata (tool_calls, etc.)")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationThread(Document):
    """Stores multi-turn LLM conversation history."""

    user_id: PydanticObjectId = Field(..., description="User who owns this thread")
    feature: str = Field(..., description="Feature context (backup_summary, workflow_assist, etc.)")
    context_ref: str | None = Field(default=None, description="Reference to related object (backup_id, workflow_id)")
    messages: list[ConversationMessage] = Field(default_factory=list, description="Conversation messages")
    mcp_config_ids: list[str] = Field(default_factory=list, description="External MCP server IDs for this thread")
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

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> None:
        """Append a message and update timestamp."""
        self.messages.append(ConversationMessage(role=role, content=content, metadata=metadata))
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


class SkillGitRepo(TimestampMixin, Document):
    """A git repository containing Agent Skills."""

    url: str = Field(..., description="Git repo URL (SSRF-validated on save)")
    branch: str = Field(default="main", description="Branch to clone/pull")
    token: str | None = Field(default=None, description="Encrypted deploy token")
    local_path: str = Field(default="", description="Absolute path to clone destination (set after first insert)")
    last_refreshed_at: datetime | None = Field(default=None, description="Last successful pull")
    error: str | None = Field(default=None, description="Last clone/pull error")

    class Settings:
        name = "skill_git_repos"
        indexes = ["url"]

    @property
    def token_set(self) -> bool:
        return self.token is not None


class Skill(TimestampMixin, Document):
    """An Agent Skill loaded from SKILL.md."""

    name: str = Field(..., description="From SKILL.md frontmatter; unique")
    description: str = Field(..., description="From SKILL.md frontmatter")
    source: Literal["direct", "git"] = Field(..., description="Skill source: 'direct' (pasted SKILL.md) or 'git' (from a repo)")
    local_path: str = Field(..., description="Absolute path to skill directory")
    enabled: bool = Field(default=True, description="Admin toggle")
    git_repo_id: PydanticObjectId | None = Field(default=None, description="FK to SkillGitRepo if source='git'")
    error: str | None = Field(default=None, description="Last parse/sync error")
    last_synced_at: datetime | None = Field(default=None, description="Last successful SKILL.md parse")

    class Settings:
        name = "skills"
        indexes = [
            IndexModel([("name", 1)], unique=True),
            "source",
            "enabled",
        ]

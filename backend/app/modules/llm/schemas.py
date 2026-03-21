"""
LLM request/response schemas.
"""

from pydantic import BaseModel, Field

# ── LLM Config CRUD ──────────────────────────────────────────────────────────


class LLMConfigCreate(BaseModel):
    """Create a new LLM configuration."""

    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(...)
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    max_tokens_per_request: int = Field(4096, ge=100, le=32000)
    is_default: bool = False
    enabled: bool = True


class LLMConfigUpdate(BaseModel):
    """Update an existing LLM configuration."""

    name: str | None = Field(None, min_length=1, max_length=100)
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens_per_request: int | None = Field(None, ge=100, le=32000)
    is_default: bool | None = None
    enabled: bool | None = None


class LLMConfigResponse(BaseModel):
    """LLM configuration response (API key masked)."""

    id: str
    name: str
    provider: str
    api_key_set: bool
    model: str | None
    base_url: str | None
    temperature: float
    max_tokens_per_request: int
    is_default: bool
    enabled: bool


class LLMConfigAvailable(BaseModel):
    """Minimal config info for workflow creators."""

    id: str
    name: str
    provider: str
    model: str | None
    is_default: bool


class LLMConnectionTestRequest(BaseModel):
    """Test connection with unsaved config values."""

    provider: str
    api_key: str | None = None
    base_url: str | None = None
    config_id: str | None = None  # Use stored key if api_key is empty


class LLMModelDiscoveryRequest(BaseModel):
    """Discover models with unsaved config values."""

    provider: str
    api_key: str | None = None
    base_url: str | None = None
    config_id: str | None = None


# ── MCP Config CRUD ──────────────────────────────────────────────────────────


class MCPConfigCreate(BaseModel):
    """Create a new MCP server configuration."""

    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(...)
    headers: dict[str, str] | None = None
    ssl_verify: bool = True
    enabled: bool = True


class MCPConfigUpdate(BaseModel):
    """Update an MCP server configuration."""

    name: str | None = Field(None, min_length=1, max_length=100)
    url: str | None = None
    headers: dict[str, str] | None = None
    ssl_verify: bool | None = None
    enabled: bool | None = None


class MCPConfigResponse(BaseModel):
    """MCP server configuration response (headers masked)."""

    id: str
    name: str
    url: str
    headers_set: bool
    ssl_verify: bool
    enabled: bool


class MCPConfigAvailable(BaseModel):
    """Minimal MCP config info for workflow creators."""

    id: str
    name: str
    url: str


class MCPConnectionTestRequest(BaseModel):
    """Test MCP connection with unsaved config values."""

    url: str
    headers: dict[str, str] | None = None
    ssl_verify: bool = True
    config_id: str | None = None


# ── Backup Summarization ─────────────────────────────────────────────────────


class SummarizeDiffRequest(BaseModel):
    """Request to summarize changes between two backup object versions."""

    version_id_1: str = Field(..., description="Older version document ID")
    version_id_2: str = Field(..., description="Newer version document ID")
    thread_id: str | None = Field(None, description="Existing conversation thread ID for follow-up")
    stream_id: str | None = Field(None, description="WebSocket stream ID for token streaming")


class SummaryResponse(BaseModel):
    """Response from an LLM summarization request."""

    summary: str
    thread_id: str
    usage: dict = Field(default_factory=dict)


# ── Conversation Follow-Up ───────────────────────────────────────────────────


class FollowUpRequest(BaseModel):
    """Request to continue a conversation thread."""

    message: str = Field(..., min_length=1, max_length=4000, description="User follow-up message")
    stream_id: str | None = Field(None, description="WebSocket stream ID for token streaming")


class ChatResponse(BaseModel):
    """Response from a follow-up conversation message."""

    reply: str
    thread_id: str
    usage: dict = Field(default_factory=dict)


# ── Workflow Creation Assistant ───────────────────────────────────────────────


class CategorySelectionRequest(BaseModel):
    """Request to select relevant API categories for a workflow description."""

    description: str = Field(..., min_length=1, max_length=4000)


class CategorySelectionResponse(BaseModel):
    """Response with selected API categories."""

    categories: list[str]
    usage: dict = Field(default_factory=dict)


class WorkflowAssistRequest(BaseModel):
    """Request to generate a workflow from natural language."""

    description: str = Field(..., min_length=1, max_length=4000)
    categories: list[str] | None = Field(None, description="Pre-selected API categories (skips pass 1)")
    thread_id: str | None = Field(None, description="Existing thread for follow-up refinements")


class WorkflowAssistResponse(BaseModel):
    """Response with generated workflow graph."""

    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    name: str = ""
    description: str = ""
    explanation: str = ""
    thread_id: str
    validation_errors: list[str] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)


class FieldAssistRequest(BaseModel):
    """Request to help fill a workflow node field."""

    node_type: str = Field(..., description="Type of the node")
    field_name: str = Field(..., description="Name of the field to fill")
    description: str = Field(..., min_length=1, max_length=2000, description="What the user wants")
    upstream_variables: dict | None = Field(None, description="Available variables from upstream nodes")


class FieldAssistResponse(BaseModel):
    """Response with a suggested field value."""

    suggested_value: str
    explanation: str = ""
    usage: dict = Field(default_factory=dict)


# ── Workflow Debugging ────────────────────────────────────────────────────────


class DebugExecutionRequest(BaseModel):
    """Request to debug a failed workflow execution."""

    execution_id: str = Field(..., description="ID of the failed execution")
    thread_id: str | None = Field(None, description="Existing thread for follow-up")
    stream_id: str | None = Field(None, description="WebSocket stream ID for token streaming")


class DebugExecutionResponse(BaseModel):
    """Response with debugging analysis."""

    analysis: str
    thread_id: str
    usage: dict = Field(default_factory=dict)


# ── Webhook Summarization ────────────────────────────────────────────────────


class WebhookSummaryRequest(BaseModel):
    """Request to summarize recent webhook events."""

    hours: int = Field(24, ge=1, le=720, description="Time range in hours")
    stream_id: str | None = Field(None, description="WebSocket stream ID for token streaming")


class WebhookSummaryResponse(BaseModel):
    """Response with webhook event summary."""

    summary: str
    event_count: int = 0
    thread_id: str
    usage: dict = Field(default_factory=dict)


# ── Global Chat ─────────────────────────────────────────────────────────────


class GlobalChatRequest(BaseModel):
    """Request for global chat with MCP tools."""

    message: str = Field(..., min_length=1, max_length=4000, description="User message")
    thread_id: str | None = Field(None, description="Existing conversation thread ID for follow-up")
    page_context: str | None = Field(None, max_length=2000, description="Current page context for the LLM")


class GlobalChatResponse(BaseModel):
    """Response from global chat."""

    reply: str
    thread_id: str
    tool_calls: list[dict] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)

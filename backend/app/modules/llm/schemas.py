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


class DebugExecutionResponse(BaseModel):
    """Response with debugging analysis."""

    analysis: str
    thread_id: str
    usage: dict = Field(default_factory=dict)


# ── Webhook Summarization ────────────────────────────────────────────────────


class WebhookSummaryRequest(BaseModel):
    """Request to summarize recent webhook events."""

    hours: int = Field(24, ge=1, le=720, description="Time range in hours")


class WebhookSummaryResponse(BaseModel):
    """Response with webhook event summary."""

    summary: str
    event_count: int = 0
    thread_id: str
    usage: dict = Field(default_factory=dict)

"""
Workflow schemas for graph-based workflow API.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowCreate(BaseModel):
    """Workflow creation schema — graph model."""

    name: str = Field(..., description="Workflow name", min_length=1, max_length=200)
    description: str | None = Field(None, description="Workflow description")
    workflow_type: str = Field(default="standard", description="Workflow type: standard or subflow")
    sharing: str | None = Field(None, description="Sharing permission: private, read-only, or read-write")
    timeout_seconds: int = Field(default=300, description="Workflow execution timeout", ge=10, le=3600)
    nodes: list[dict[str, Any]] = Field(..., description="Graph nodes", min_length=1)
    edges: list[dict[str, Any]] = Field(default_factory=list, description="Graph edges")
    viewport: dict | None = Field(None, description="Canvas viewport state")
    input_parameters: list[dict[str, Any]] = Field(default_factory=list, description="Sub-flow input parameters")
    output_parameters: list[dict[str, Any]] = Field(default_factory=list, description="Sub-flow output parameters")


class WorkflowUpdate(BaseModel):
    """Workflow update schema — graph model."""

    name: str | None = Field(None, description="Workflow name", min_length=1, max_length=200)
    description: str | None = Field(None, description="Workflow description")
    status: str | None = Field(None, description="Workflow status")
    sharing: str | None = Field(None, description="Sharing permission: private, read-only, or read-write")
    timeout_seconds: int | None = Field(None, description="Workflow execution timeout", ge=10, le=3600)
    nodes: list[dict[str, Any]] | None = Field(None, description="Graph nodes")
    edges: list[dict[str, Any]] | None = Field(None, description="Graph edges")
    viewport: dict | None = Field(None, description="Canvas viewport state")
    input_parameters: list[dict[str, Any]] | None = Field(None, description="Sub-flow input parameters")
    output_parameters: list[dict[str, Any]] | None = Field(None, description="Sub-flow output parameters")


class WorkflowResponse(BaseModel):
    """Workflow response schema — graph model."""

    id: str = Field(..., description="Workflow ID")
    name: str = Field(..., description="Workflow name")
    description: str | None = Field(None, description="Workflow description")
    workflow_type: str = Field(default="standard", description="Workflow type")
    created_by: str = Field(..., description="Creator user ID")
    status: str = Field(..., description="Workflow status")
    sharing: str = Field(..., description="Sharing permission")
    timeout_seconds: int = Field(..., description="Execution timeout")
    nodes: list[dict[str, Any]] = Field(..., description="Graph nodes")
    edges: list[dict[str, Any]] = Field(..., description="Graph edges")
    viewport: dict | None = Field(None, description="Canvas viewport state")
    input_parameters: list[dict[str, Any]] = Field(default_factory=list, description="Sub-flow input parameters")
    output_parameters: list[dict[str, Any]] = Field(default_factory=list, description="Sub-flow output parameters")
    execution_count: int = Field(..., description="Total executions")
    success_count: int = Field(..., description="Successful executions")
    failure_count: int = Field(..., description="Failed executions")
    active_windows: list[dict[str, Any]] = Field(default_factory=list, description="Active aggregation windows")
    last_execution: datetime | None = Field(None, description="Last execution timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True


class SubflowSchemaResponse(BaseModel):
    """Sub-flow schema response — input/output parameter definitions."""

    id: str = Field(..., description="Workflow ID")
    name: str = Field(..., description="Workflow name")
    input_parameters: list[dict[str, Any]] = Field(default_factory=list, description="Input parameters")
    output_parameters: list[dict[str, Any]] = Field(default_factory=list, description="Output parameters")


class WorkflowListResponse(BaseModel):
    """Workflow list response schema."""

    workflows: list[WorkflowResponse] = Field(..., description="List of workflows")
    total: int = Field(..., description="Total number of workflows")


class InlineGraphRequest(BaseModel):
    """Request body for computing available variables from an in-memory graph."""

    nodes: list[dict[str, Any]] = Field(..., description="Graph nodes")
    edges: list[dict[str, Any]] = Field(default_factory=list, description="Graph edges")
    input_parameters: list[dict[str, Any]] = Field(default_factory=list, description="Subflow input parameters")


class SimulateRequest(BaseModel):
    """Simulation request schema."""

    payload: dict[str, Any] | None = Field(None, description="Custom trigger payload")
    webhook_event_id: str | None = Field(None, description="Use payload from an existing webhook event")
    dry_run: bool = Field(default=True, description="Mock external API/webhook calls")
    stream_id: str | None = Field(None, description="WebSocket channel suffix for streaming progress")

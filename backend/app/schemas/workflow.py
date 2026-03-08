"""
Workflow schemas.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowCreate(BaseModel):
    """Workflow creation schema."""

    name: str = Field(..., description="Workflow name", min_length=1, max_length=200)
    description: str | None = Field(None, description="Workflow description")
    timeout_seconds: int = Field(default=300, description="Workflow execution timeout", ge=10, le=3600)
    trigger: dict[str, Any] = Field(..., description="Trigger configuration")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="Primary filters")
    secondary_filters: list[dict[str, Any]] = Field(default_factory=list, description="Secondary filters")
    actions: list[dict[str, Any]] = Field(..., description="Actions to execute", min_length=1)


class WorkflowUpdate(BaseModel):
    """Workflow update schema."""

    name: str | None = Field(None, description="Workflow name", min_length=1, max_length=200)
    description: str | None = Field(None, description="Workflow description")
    status: str | None = Field(None, description="Workflow status")
    timeout_seconds: int | None = Field(None, description="Workflow execution timeout", ge=10, le=3600)
    trigger: dict[str, Any] | None = Field(None, description="Trigger configuration")
    filters: list[dict[str, Any]] | None = Field(None, description="Primary filters")
    secondary_filters: list[dict[str, Any]] | None = Field(None, description="Secondary filters")
    actions: list[dict[str, Any]] | None = Field(None, description="Actions to execute")


class WorkflowResponse(BaseModel):
    """Workflow response schema."""

    id: str = Field(..., description="Workflow ID")
    name: str = Field(..., description="Workflow name")
    description: str | None = Field(None, description="Workflow description")
    created_by: str = Field(..., description="Creator user ID")
    status: str = Field(..., description="Workflow status")
    sharing: str = Field(..., description="Sharing permission")
    timeout_seconds: int = Field(..., description="Execution timeout")
    trigger: dict[str, Any] = Field(..., description="Trigger configuration")
    filters: list[dict[str, Any]] = Field(..., description="Primary filters")
    secondary_filters: list[dict[str, Any]] = Field(..., description="Secondary filters")
    actions: list[dict[str, Any]] = Field(..., description="Actions")
    execution_count: int = Field(..., description="Total executions")
    success_count: int = Field(..., description="Successful executions")
    failure_count: int = Field(..., description="Failed executions")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    """Workflow list response schema."""

    workflows: list[WorkflowResponse] = Field(..., description="List of workflows")
    total: int = Field(..., description="Total number of workflows")

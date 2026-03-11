"""
Workflow execution model for tracking workflow runs — graph-aware.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    """Execution status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    FILTERED = "filtered"
    PARTIAL = "partial"


class NodeExecutionResult(BaseModel):
    """Result of executing a single graph node."""
    node_id: str = Field(..., description="Node ID in the graph")
    node_name: str = Field(default="", description="Node display name")
    node_type: str = Field(default="", description="Node type (action type or 'trigger')")
    status: str = Field(..., description="Execution status: success, failed, skipped")
    started_at: datetime = Field(..., description="Node execution start time")
    completed_at: datetime | None = Field(default=None, description="Node execution end time")
    duration_ms: int | None = Field(default=None, description="Duration in milliseconds")
    error: str | None = Field(default=None, description="Error message if failed")
    output_data: dict | None = Field(default=None, description="Node output data")
    input_snapshot: dict | None = Field(default=None, description="Variables available to this node at execution time")
    retry_count: int = Field(default=0, description="Number of retries attempted")


class NodeSnapshot(BaseModel):
    """Full snapshot of a node execution for simulation replay."""
    node_id: str
    node_name: str = ""
    step: int = 0
    input_variables: dict[str, Any] = Field(default_factory=dict)
    output_data: dict[str, Any] | None = None
    status: str = "pending"
    duration_ms: int | None = None
    error: str | None = None
    variables_after: dict[str, Any] = Field(default_factory=dict)


class WorkflowExecution(Document):
    """Workflow execution tracking model — graph-aware."""

    workflow_id: PydanticObjectId = Field(..., description="Reference to workflow")
    workflow_name: str = Field(..., description="Workflow name (for history)")

    # Execution status
    status: ExecutionStatus = Field(default=ExecutionStatus.PENDING, description="Execution status")

    # Trigger information
    trigger_type: str = Field(..., description="Trigger type: webhook, cron, manual")
    trigger_data: dict | None = Field(default=None, description="Trigger data (webhook payload, etc.)")
    triggered_by: PydanticObjectId | None = Field(default=None, description="User ID if manually triggered")

    # Execution details
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = Field(default=None, description="Execution completion time")
    duration_ms: int | None = Field(default=None, description="Total execution duration in milliseconds")

    # Trigger condition evaluation
    trigger_condition_passed: bool | None = Field(default=None)
    trigger_condition: str | None = Field(default=None)

    # Node execution results — keyed by node_id
    node_results: dict[str, NodeExecutionResult] = Field(default_factory=dict, description="Per-node execution results")

    # Aggregate counters
    nodes_executed: int = Field(default=0)
    nodes_succeeded: int = Field(default=0)
    nodes_failed: int = Field(default=0)

    # Simulation snapshots (populated in debug/simulate mode)
    node_snapshots: list[NodeSnapshot] = Field(default_factory=list, description="Step-by-step snapshots for replay")
    is_simulation: bool = Field(default=False, description="Whether this was a simulation run")
    is_dry_run: bool = Field(default=False, description="Whether external calls were mocked")

    # Error handling
    error: str | None = Field(default=None, description="Error message if execution failed")
    error_details: dict | None = Field(default=None, description="Detailed error information")

    # Execution context
    variables: dict = Field(default_factory=dict, description="Variables extracted during execution")

    # Logs
    logs: list[str] = Field(default_factory=list, description="Execution log messages")

    class Settings:
        name = "workflow_executions"
        indexes = [
            "workflow_id",
            "status",
            [("started_at", -1)],
            "trigger_type",
            "triggered_by",
        ]

    def add_log(self, message: str, level: str = "info"):
        """Add a log message."""
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = f"[{timestamp}] [{level.upper()}] {message}"
        self.logs.append(log_entry)

    def add_node_result(self, result: NodeExecutionResult):
        """Add a node execution result."""
        self.node_results[result.node_id] = result
        self.nodes_executed += 1

        if result.status == "success":
            self.nodes_succeeded += 1
        elif result.status == "failed":
            self.nodes_failed += 1

    def mark_completed(self, status: ExecutionStatus, error: str | None = None):
        """Mark execution as completed."""
        self.status = status
        self.completed_at = datetime.now(timezone.utc)

        if self.started_at and self.completed_at:
            started = self.started_at if self.started_at.tzinfo else self.started_at.replace(tzinfo=timezone.utc)
            completed = self.completed_at if self.completed_at.tzinfo else self.completed_at.replace(tzinfo=timezone.utc)
            delta = completed - started
            self.duration_ms = int(delta.total_seconds() * 1000)

        if error:
            self.error = error

    def get_summary(self) -> dict:
        """Get execution summary."""
        return {
            "execution_id": str(self.id),
            "workflow_name": self.workflow_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "nodes_executed": self.nodes_executed,
            "nodes_succeeded": self.nodes_succeeded,
            "nodes_failed": self.nodes_failed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    class Config:
        json_schema_extra = {
            "example": {
                "workflow_id": "507f1f77bcf86cd799439011",
                "workflow_name": "AP Offline Alert",
                "status": "success",
                "trigger_type": "webhook",
                "trigger_condition_passed": True,
                "nodes_executed": 2,
                "nodes_succeeded": 2,
                "nodes_failed": 0,
                "duration_ms": 1250,
            }
        }

"""
Workflow execution model for tracking workflow runs.
"""

from datetime import datetime, timezone
from enum import Enum

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


class ActionExecutionResult(BaseModel):
    """Result of a single action execution."""
    action_name: str = Field(..., description="Name of the action")
    status: str = Field(..., description="Action execution status: success, failed, skipped")
    started_at: datetime = Field(..., description="Action start time")
    completed_at: datetime | None = Field(default=None, description="Action completion time")
    duration_ms: int | None = Field(default=None, description="Action duration in milliseconds")
    error: str | None = Field(default=None, description="Error message if failed")
    output: dict | None = Field(default=None, description="Action output data")
    retry_count: int = Field(default=0, description="Number of retries attempted")


class WorkflowExecution(Document):
    """Workflow execution tracking model."""

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
    trigger_condition_passed: bool | None = Field(default=None, description="Whether trigger condition passed (None if no condition)")
    trigger_condition: str | None = Field(default=None, description="The trigger condition expression that was evaluated")
    
    # Action execution
    actions_executed: int = Field(default=0, description="Number of actions executed")
    actions_succeeded: int = Field(default=0, description="Number of actions that succeeded")
    actions_failed: int = Field(default=0, description="Number of actions that failed")
    action_results: list[ActionExecutionResult] = Field(default_factory=list, description="Individual action results")
    
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
            [("started_at", -1)],  # Descending order for recent executions
            "trigger_type",
            "triggered_by",
        ]
    
    def add_log(self, message: str, level: str = "info"):
        """Add a log message."""
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = f"[{timestamp}] [{level.upper()}] {message}"
        self.logs.append(log_entry)
    
    def add_action_result(self, result: ActionExecutionResult):
        """Add an action execution result."""
        self.action_results.append(result)
        self.actions_executed += 1
        
        if result.status == "success":
            self.actions_succeeded += 1
        elif result.status == "failed":
            self.actions_failed += 1
    
    def mark_completed(self, status: ExecutionStatus, error: str | None = None):
        """Mark execution as completed."""
        self.status = status
        self.completed_at = datetime.now(timezone.utc)

        if self.started_at and self.completed_at:
            # Ensure both datetimes are aware — MongoDB may return naive UTC
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
            "actions_executed": self.actions_executed,
            "actions_succeeded": self.actions_succeeded,
            "actions_failed": self.actions_failed,
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
                "actions_executed": 2,
                "actions_succeeded": 2,
                "actions_failed": 0,
                "duration_ms": 1250,
            }
        }

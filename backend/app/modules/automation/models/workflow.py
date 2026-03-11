"""
Workflow model for automation engine — graph-based node/edge model.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field

from app.models.mixins import TimestampMixin


class WorkflowStatus(str, Enum):
    """Workflow status enumeration."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    DRAFT = "draft"


class SharingPermission(str, Enum):
    """Workflow sharing permission levels."""
    PRIVATE = "private"
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"


class TriggerType(str, Enum):
    """Trigger type enumeration."""
    WEBHOOK = "webhook"
    CRON = "cron"


class ActionType(str, Enum):
    """Action type enumeration."""
    MIST_API_GET = "mist_api_get"
    MIST_API_POST = "mist_api_post"
    MIST_API_PUT = "mist_api_put"
    MIST_API_DELETE = "mist_api_delete"
    WEBHOOK = "webhook"
    SLACK = "slack"
    SERVICENOW = "servicenow"
    PAGERDUTY = "pagerduty"
    DELAY = "delay"
    CONDITION = "condition"
    SET_VARIABLE = "set_variable"
    FOR_EACH = "for_each"


class VariableBinding(BaseModel):
    """A variable binding: extracts a value from output into a named variable."""
    name: str = Field(..., description="Variable name to store as")
    expression: str = Field(default="", description="Jinja2 expression to extract from output; empty = full output")


# ── Graph models ──────────────────────────────────────────────────────────────


class NodePosition(BaseModel):
    """2D position of a node on the canvas."""
    x: float = 0
    y: float = 0


class NodePort(BaseModel):
    """An input or output port on a node."""
    id: str = Field(..., description="Port ID, e.g. 'default', 'branch_0', 'else', 'loop_body', 'done'")
    label: str = ""
    type: str = "default"  # default | branch | loop_body | loop_done


class WorkflowNode(BaseModel):
    """A single node in the workflow graph."""
    id: str = Field(..., description="Persistent UUID for this node")
    type: str = Field(..., description="'trigger' or an ActionType value")
    name: str = ""
    position: NodePosition = Field(default_factory=NodePosition)
    config: dict[str, Any] = Field(default_factory=dict, description="Type-specific configuration")
    output_ports: list[NodePort] = Field(default_factory=list, description="Output ports (derived from type)")
    enabled: bool = True
    continue_on_error: bool = False
    max_retries: int = 3
    retry_delay: int = 5
    save_as: list[VariableBinding] | None = None


class WorkflowEdge(BaseModel):
    """A directed edge connecting two nodes."""
    id: str = Field(..., description="Unique edge ID")
    source_node_id: str = Field(..., description="Source node ID")
    source_port_id: str = Field(default="default", description="Source port ID")
    target_node_id: str = Field(..., description="Target node ID")
    target_port_id: str = Field(default="input", description="Target port ID")
    label: str = ""


# ── Workflow document ─────────────────────────────────────────────────────────


class Workflow(TimestampMixin, Document):
    """Workflow configuration model — graph-based."""

    # Basic info
    name: str = Field(..., description="Workflow name")
    description: str | None = Field(default=None, description="Workflow description")

    # Ownership and permissions
    created_by: PydanticObjectId = Field(..., description="User ID who created the workflow")
    status: WorkflowStatus = Field(default=WorkflowStatus.DRAFT, description="Workflow status")
    sharing: SharingPermission = Field(default=SharingPermission.PRIVATE, description="Sharing permission")

    # Configuration — graph model
    timeout_seconds: int = Field(default=300, description="Workflow execution timeout in seconds")
    nodes: list[WorkflowNode] = Field(default_factory=list, description="Graph nodes")
    edges: list[WorkflowEdge] = Field(default_factory=list, description="Graph edges")
    viewport: dict | None = Field(default=None, description="Canvas viewport state (pan/zoom)")

    # Statistics
    execution_count: int = Field(default=0, description="Total number of executions")
    success_count: int = Field(default=0, description="Number of successful executions")
    failure_count: int = Field(default=0, description="Number of failed executions")
    last_execution: datetime | None = Field(default=None, description="Last execution timestamp")
    last_success: datetime | None = Field(default=None, description="Last successful execution timestamp")
    last_failure: datetime | None = Field(default=None, description="Last failed execution timestamp")

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "workflows"
        indexes = [
            "name",
            "created_by",
            "status",
            "last_execution",
        ]

    def can_be_accessed_by(self, user: "User") -> bool:
        """Check if user can access this workflow."""
        from app.models.user import User

        if user.is_admin():
            return True
        if self.created_by == user.id:
            return True
        if self.sharing == SharingPermission.PRIVATE:
            return False
        if user.can_manage_workflows():
            return True
        return False

    def can_be_modified_by(self, user: "User") -> bool:
        """Check if user can modify this workflow."""
        from app.models.user import User

        if user.is_admin():
            return True
        if self.created_by == user.id:
            return True
        if self.sharing == SharingPermission.READ_WRITE and user.can_manage_workflows():
            return True
        return False

    def increment_execution_stats(self, success: bool):
        """Increment execution statistics."""
        self.execution_count += 1
        self.last_execution = datetime.now(timezone.utc)

        if success:
            self.success_count += 1
            self.last_success = datetime.now(timezone.utc)
        else:
            self.failure_count += 1
            self.last_failure = datetime.now(timezone.utc)

    def get_trigger_node(self) -> WorkflowNode | None:
        """Find the trigger node in the graph."""
        for node in self.nodes:
            if node.type == "trigger":
                return node
        return None

    def get_node_by_id(self, node_id: str) -> WorkflowNode | None:
        """Find a node by its ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "AP Offline Alert",
                "description": "Send notification when AP goes offline",
                "status": "enabled",
                "sharing": "private",
                "timeout_seconds": 300,
                "nodes": [
                    {
                        "id": "trigger-1",
                        "type": "trigger",
                        "name": "Webhook Trigger",
                        "position": {"x": 400, "y": 80},
                        "config": {
                            "trigger_type": "webhook",
                            "webhook_type": "alarm",
                            "webhook_topic": "ap_offline",
                        },
                        "output_ports": [{"id": "default", "label": "", "type": "default"}],
                    },
                    {
                        "id": "action-1",
                        "type": "slack",
                        "name": "Send Slack notification",
                        "position": {"x": 400, "y": 240},
                        "config": {
                            "notification_channel": "#alerts",
                            "notification_template": "AP {device_name} went offline",
                        },
                        "output_ports": [{"id": "default", "label": "", "type": "default"}],
                    },
                ],
                "edges": [
                    {
                        "id": "edge-1",
                        "source_node_id": "trigger-1",
                        "source_port_id": "default",
                        "target_node_id": "action-1",
                        "target_port_id": "input",
                    }
                ],
            }
        }

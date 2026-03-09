"""
Workflow model for automation engine.
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


class WorkflowTrigger(BaseModel):
    """Workflow trigger configuration."""
    type: TriggerType = Field(..., description="Trigger type: webhook or cron")
    webhook_type: str | None = Field(default=None, description="Mist webhook topic (alarms, audits, device-events, …)")
    webhook_topic: str | None = Field(default=None, description="Mist event type filter (e.g. ap_offline)")
    cron_expression: str | None = Field(default=None, description="Cron expression for scheduled execution")
    timezone: str | None = Field(default="UTC", description="Timezone for cron execution")
    skip_if_running: bool = Field(default=True, description="Skip execution if workflow is already running")
    condition: str | None = Field(default=None, description="Jinja2 gate expression — if falsy, workflow exits with FILTERED status")
    save_as: list[VariableBinding] | None = Field(default=None, description="Variables to extract from trigger payload")


class ConditionBranch(BaseModel):
    """A single branch in a condition action (if / else-if)."""
    condition: str = Field(..., description="Condition expression to evaluate")
    actions: list["WorkflowAction"] = Field(..., description="Actions to execute if condition is true")


class WorkflowAction(BaseModel):
    """Workflow action configuration."""
    name: str = Field(..., description="Action name for identification")
    type: ActionType = Field(..., description="Action type")
    enabled: bool = Field(default=True, description="Whether action is enabled")

    # API action parameters
    api_endpoint: str | None = Field(default=None, description="API endpoint (for Mist API actions)")
    api_method: str | None = Field(default=None, description="HTTP method override")
    api_body: dict | None = Field(default=None, description="Request body (supports variable substitution)")
    api_params: dict | None = Field(default=None, description="Query parameters")

    # Webhook action parameters
    webhook_url: str | None = Field(default=None, description="Webhook URL to call")
    webhook_headers: dict | None = Field(default=None, description="Custom headers for webhook")
    webhook_body: dict | None = Field(default=None, description="Webhook payload")

    # Notification parameters
    notification_template: str | None = Field(default=None, description="Message template with variables")
    notification_channel: str | None = Field(default=None, description="Slack channel, ServiceNow table, etc.")

    # Conditional logic (multi-branch: if / else-if / else)
    branches: list[ConditionBranch] | None = Field(default=None, description="Condition branches evaluated in order (if / else-if)")
    else_actions: list["WorkflowAction"] | None = Field(default=None, description="Fallback actions if no branch matches (else)")

    # Delay action
    delay_seconds: int | None = Field(default=None, description="Delay duration in seconds")

    # Variable storage (save_as) — list of variable bindings extracted from action output
    save_as: list["VariableBinding"] | None = Field(default=None, description="Variables to extract from action output")

    # SET_VARIABLE action
    variable_name: str | None = Field(default=None, description="Variable name for set_variable action")
    variable_expression: str | None = Field(default=None, description="Jinja2 expression for set_variable action")

    # FOR_EACH loop
    loop_over: str | None = Field(default=None, description="Dot-path into variable context to iterate (e.g. results.sites)")
    loop_variable: str | None = Field(default=None, description="Name for the current loop item (e.g. site)")
    loop_actions: list["WorkflowAction"] | None = Field(default=None, description="Nested actions to execute for each item")
    max_iterations: int = Field(default=100, description="Safety cap on loop iterations")

    # Retry configuration
    max_retries: int = Field(default=3, description="Maximum number of retries on failure")
    retry_delay: int = Field(default=5, description="Delay between retries in seconds")

    # Continue on error
    continue_on_error: bool = Field(default=False, description="Continue workflow if action fails")


class Workflow(TimestampMixin, Document):
    """Workflow configuration model."""
    
    # Basic info
    name: str = Field(..., description="Workflow name")
    description: str | None = Field(default=None, description="Workflow description")

    # Ownership and permissions
    created_by: PydanticObjectId = Field(..., description="User ID who created the workflow")
    status: WorkflowStatus = Field(default=WorkflowStatus.DRAFT, description="Workflow status")
    sharing: SharingPermission = Field(default=SharingPermission.PRIVATE, description="Sharing permission")

    # Configuration
    timeout_seconds: int = Field(default=300, description="Workflow execution timeout in seconds")
    trigger: WorkflowTrigger = Field(..., description="Trigger configuration")
    actions: list[WorkflowAction] = Field(..., description="Actions to execute")

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
            "trigger.type",
            "last_execution",
        ]
    
    def can_be_accessed_by(self, user: "User") -> bool:
        """Check if user can access this workflow."""
        from app.models.user import User
        
        # Admins can access all workflows
        if user.is_admin():
            return True
        
        # Creator always has access
        if self.created_by == user.id:
            return True
        
        # Check sharing permissions
        if self.sharing == SharingPermission.PRIVATE:
            return False
        
        # Read-only or read-write allows viewing
        if user.can_manage_workflows():
            return True
        
        return False
    
    def can_be_modified_by(self, user: "User") -> bool:
        """Check if user can modify this workflow."""
        from app.models.user import User
        
        # Admins can modify all workflows
        if user.is_admin():
            return True
        
        # Creator can modify their own workflows
        if self.created_by == user.id:
            return True
        
        # Read-write sharing allows modification
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
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "AP Offline Alert",
                "description": "Send notification when AP goes offline",
                "status": "enabled",
                "sharing": "private",
                "timeout_seconds": 300,
                "trigger": {
                    "type": "webhook",
                    "webhook_type": "alarm",
                    "webhook_topic": "ap_offline",
                    "condition": "{{ events[0].type == 'ap_offline' }}",
                },
                "actions": [
                    {
                        "name": "Send Slack notification",
                        "type": "slack",
                        "notification_channel": "#alerts",
                        "notification_template": "AP {device_name} went offline",
                    }
                ],
            }
        }

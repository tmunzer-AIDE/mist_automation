"""
System configuration and audit logging models.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field

from app.models.mixins import TimestampMixin


class SystemConfig(TimestampMixin, Document):
    """System-wide configuration settings."""
    
    # Singleton pattern - only one document should exist
    config_version: int = Field(default=1, description="Configuration version")
    
    # Mist API Configuration
    mist_api_token: str | None = Field(default=None, description="Encrypted Mist API token")
    mist_org_id: str | None = Field(default=None, description="Mist Organization ID")
    mist_cloud_region: str = Field(default="global", description="Mist cloud region")
    
    # Webhook Configuration
    webhook_secret: str | None = Field(default=None, description="Webhook validation secret")
    webhook_ip_whitelist: list[str] = Field(default_factory=list, description="Allowed webhook source IPs")

    # Smee.io Configuration (webhook proxy for development)
    smee_enabled: bool = Field(default=False, description="Enable Smee.io webhook forwarding")
    smee_channel_url: str | None = Field(default=None, description="Smee.io channel URL")
    
    # Workflow Execution Limits
    max_concurrent_workflows: int = Field(default=10, description="Maximum concurrent workflow executions")
    workflow_default_timeout: int = Field(default=300, description="Default workflow timeout in seconds")
    workflow_max_timeout: int = Field(default=3600, description="Maximum allowed workflow timeout")
    
    # Password Policy
    min_password_length: int = Field(default=12, description="Minimum password length")
    require_uppercase: bool = Field(default=True, description="Require uppercase letters")
    require_lowercase: bool = Field(default=True, description="Require lowercase letters")
    require_digits: bool = Field(default=True, description="Require digits")
    require_special_chars: bool = Field(default=True, description="Require special characters")

    # Session Management
    session_timeout_hours: int = Field(default=24, description="Session timeout in hours")
    max_concurrent_sessions: int = Field(default=5, description="Max concurrent sessions per user")

    # Backup Configuration
    backup_enabled: bool = Field(default=True, description="Enable automatic backups")
    backup_full_schedule_cron: str = Field(default="0 2 * * *", description="Full backup cron schedule")
    backup_retention_days: int = Field(default=90, description="Backup retention in days")
    backup_git_enabled: bool = Field(default=False, description="Enable Git backup integration")
    backup_git_repo_url: str | None = Field(default=None, description="Git repository URL")
    backup_git_branch: str = Field(default="main", description="Git branch name")
    backup_git_author_name: str = Field(default="Mist Automation", description="Git commit author name")
    backup_git_author_email: str = Field(default="automation@example.com", description="Git commit author email")

    # External Integrations
    slack_workspace_url: str | None = Field(default=None, description="Slack workspace URL")
    slack_app_token: str | None = Field(default=None, description="Encrypted Slack app token")
    slack_webhook_url: str | None = Field(default=None, description="Slack webhook URL")

    servicenow_instance_url: str | None = Field(default=None, description="ServiceNow instance URL")
    servicenow_username: str | None = Field(default=None, description="ServiceNow username")
    servicenow_password: str | None = Field(default=None, description="Encrypted ServiceNow password")

    pagerduty_api_key: str | None = Field(default=None, description="Encrypted PagerDuty API key")
    
    # LLM Configuration (individual configs stored in LLMConfig collection)
    llm_enabled: bool = Field(default=False, description="Global LLM kill switch")

    # System Status
    is_initialized: bool = Field(default=False, description="Whether initial setup is complete")
    maintenance_mode: bool = Field(default=False, description="Whether system is in maintenance mode")
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Settings:
        name = "system_config"
    
    @classmethod
    async def get_config(cls) -> "SystemConfig":
        """Get the system configuration (creates if doesn't exist).

        Uses insert with DuplicateKeyError handling to avoid race conditions
        when two concurrent requests both find no config.
        """
        config = await cls.find_one()
        if config:
            return config
        try:
            config = cls()
            await config.insert()
            return config
        except Exception:
            # Another request may have inserted concurrently — re-fetch
            config = await cls.find_one()
            if config:
                return config
            raise
    
    class Config:
        json_schema_extra = {
            "example": {
                "config_version": 1,
                "mist_org_id": "2818e386-8dec-2562-9ede-5b8a0fbbdc71",
                "mist_cloud_region": "global",
                "max_concurrent_workflows": 10,
                "session_timeout_hours": 24,
                "is_initialized": True,
                "maintenance_mode": False,
            }
        }


class AuditLog(Document):
    """Audit log for tracking user actions and system events."""
    
    # Event information
    event_type: str = Field(..., description="Type of event (e.g., user_login, workflow_created)")
    event_category: str = Field(..., description="Category: auth, workflow, backup, system, etc.")
    description: str = Field(..., description="Human-readable event description")

    # Actor information
    user_id: PydanticObjectId | None = Field(default=None, description="User who performed the action")
    user_email: str | None = Field(default=None, description="User email (cached for display)")
    source_ip: str | None = Field(default=None, description="Source IP address")
    user_agent: str | None = Field(default=None, description="User agent string")

    # Target information
    target_type: str | None = Field(default=None, description="Type of resource affected")
    target_id: str | None = Field(default=None, description="ID of resource affected")
    target_name: str | None = Field(default=None, description="Name of resource affected")
    
    # Event details
    details: dict = Field(default_factory=dict, description="Additional event details")
    changes: dict | None = Field(default=None, description="Before/after values for modifications")
    
    # Status
    success: bool = Field(default=True, description="Whether the action was successful")
    error_message: str | None = Field(default=None, description="Error message if action failed")
    
    # Timestamp
    timestamp: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    class Settings:
        name = "audit_logs"
        indexes = [
            [("timestamp", -1)],  # Descending for recent first
            "event_type",
            "event_category",
            "user_id",
            "target_type",
            "success",
        ]
    
    @classmethod
    async def log_event(
        cls,
        event_type: str,
        event_category: str,
        description: str,
        user_id: PydanticObjectId | None = None,
        user_email: str | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        target_name: str | None = None,
        details: dict | None = None,
        changes: dict | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> "AuditLog":
        """Create and save an audit log entry."""
        log = cls(
            event_type=event_type,
            event_category=event_category,
            description=description,
            user_id=user_id,
            user_email=user_email,
            source_ip=source_ip,
            user_agent=user_agent,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            details=details or {},
            changes=changes,
            success=success,
            error_message=error_message,
        )
        await log.insert()
        return log
    
    class Config:
        json_schema_extra = {
            "example": {
                "event_type": "workflow_created",
                "event_category": "workflow",
                "description": "Created new workflow: AP Offline Alert",
                "user_email": "admin@example.com",
                "source_ip": "192.168.1.100",
                "target_type": "workflow",
                "target_id": "507f1f77bcf86cd799439011",
                "target_name": "AP Offline Alert",
                "success": True,
            }
        }

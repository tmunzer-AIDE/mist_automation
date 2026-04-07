"""
Admin request/response schemas.
"""

from urllib.parse import urlparse

from croniter import croniter
from pydantic import BaseModel, Field, field_validator


class SystemSettingsUpdate(BaseModel):
    """Schema for PUT /admin/settings — partial update of system configuration."""

    # Mist API
    mist_api_token: str | None = None
    mist_org_id: str | None = None
    mist_cloud_region: str | None = None
    webhook_secret: str | None = None

    # Workflow limits
    max_concurrent_workflows: int | None = Field(None, ge=1, le=100)
    workflow_default_timeout: int | None = Field(None, ge=10, le=3600)

    # Password Policy
    min_password_length: int | None = Field(None, ge=8, le=128)
    require_uppercase: bool | None = None
    require_lowercase: bool | None = None
    require_digits: bool | None = None
    require_special_chars: bool | None = None

    # Session
    session_timeout_hours: int | None = Field(None, ge=1, le=720)
    max_concurrent_sessions: int | None = Field(None, ge=1, le=100)

    # Backup
    backup_enabled: bool | None = None
    backup_full_schedule_cron: str | None = None
    backup_retention_days: int | None = Field(None, ge=1, le=3650)
    backup_git_enabled: bool | None = None
    backup_git_repo_url: str | None = None
    backup_git_branch: str | None = None
    backup_git_author_name: str | None = None
    backup_git_author_email: str | None = None

    # Smee.io
    smee_enabled: bool | None = None
    smee_channel_url: str | None = None

    # External integrations (non-sensitive)
    slack_webhook_url: str | None = None
    servicenow_instance_url: str | None = None
    servicenow_username: str | None = None

    # Sensitive integration fields
    servicenow_password: str | None = None
    pagerduty_api_key: str | None = None
    slack_signing_secret: str | None = None

    # Webhook IP allowlist
    webhook_ip_whitelist: list[str] | None = None

    # Execution retention
    execution_retention_days: int | None = Field(None, ge=1, le=3650)

    # Maintenance mode
    maintenance_mode: bool | None = None

    # Email / SMTP
    smtp_host: str | None = None
    smtp_port: int | None = Field(None, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool | None = None

    # LLM (global toggle only — individual configs managed via /llm/configs)
    llm_enabled: bool | None = None

    # LLM Memory
    memory_enabled: bool | None = None
    memory_max_entries_per_user: int | None = Field(None, ge=10, le=500)
    memory_entry_max_length: int | None = Field(None, ge=100, le=2000)
    memory_consolidation_enabled: bool | None = None
    memory_consolidation_cron: str | None = None

    # Impact Analysis
    impact_analysis_enabled: bool | None = None
    impact_analysis_default_duration_minutes: int | None = Field(None, ge=1, le=360)
    impact_analysis_default_interval_minutes: int | None = Field(None, ge=1, le=60)
    impact_analysis_sle_threshold_percent: float | None = Field(None, ge=1.0, le=50.0)
    impact_analysis_retention_days: int | None = Field(None, ge=1, le=365)

    @field_validator("webhook_ip_whitelist")
    @classmethod
    def validate_ip_whitelist(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        import ipaddress

        for entry in v:
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError as e:
                raise ValueError(f"Invalid IP/CIDR '{entry}': {e}") from e
        return v

    @field_validator("backup_full_schedule_cron", "memory_consolidation_cron")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            croniter(v)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid cron expression: {e}") from e
        return v

    @field_validator(
        "backup_git_repo_url", "slack_webhook_url", "servicenow_instance_url", "smee_channel_url"
    )
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL scheme must be http or https")
        if not parsed.netloc:
            raise ValueError("URL must include a domain")
        return v

    @field_validator("smee_channel_url")
    @classmethod
    def validate_smee_url(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if not v.startswith("https://smee.io/"):
            raise ValueError("Smee channel URL must start with https://smee.io/")
        return v

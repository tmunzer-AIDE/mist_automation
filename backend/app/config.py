"""
Application configuration management using Pydantic settings.
Loads configuration from environment variables and .env files.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    app_name: str = "Mist Automation & Backup"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = Field(default="development", description="Environment: development, staging, production")
    
    # API
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default=["http://localhost:4200", "http://localhost:8080"],
        description="Allowed CORS origins (comma-separated in .env)"
    )
    
    # Security
    secret_key: str = Field(..., description="Secret key for JWT tokens - must be set in environment")
    algorithm: str = "HS256"
    access_token_expire_hours: int = 24
    refresh_token_expire_days: int = 30
    
    # Password Policy
    min_password_length: int = 8
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_digits: bool = True
    require_special_chars: bool = False
    
    # Session Management
    max_concurrent_sessions: int = 5
    device_trust_days: int = 30
    
    # MongoDB
    mongodb_url: str = Field(default="mongodb://localhost:27017", description="MongoDB connection URL")
    mongodb_db_name: str = Field(default="mist_automation", description="MongoDB database name")
    mongodb_min_pool_size: int = 10
    mongodb_max_pool_size: int = 100
    mongodb_username: str | None = Field(default=None, description="MongoDB username")
    mongodb_password: str | None = Field(default=None, description="MongoDB password")
    
    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    redis_max_connections: int = 50
    
    # Mist API
    mist_api_token: str | None = Field(default=None, description="Mist API token (encrypted in DB)")
    mist_org_id: str | None = Field(default=None, description="Mist Organization ID")
    mist_cloud_region: str = Field(default="global", description="Mist cloud region: global, eu, apac")
    mist_api_timeout: int = 30
    mist_api_max_retries: int = 3
    
    # Workflow Execution
    max_concurrent_workflows: int = 10
    workflow_default_timeout: int = 300  # 5 minutes
    workflow_max_timeout: int = 3600  # 1 hour
    webhook_dedup_ttl: int = 300  # 5 minutes
    
    # Background Tasks
    celery_broker_url: str = Field(default="redis://localhost:6379/1", description="Celery broker URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/2", description="Celery result backend URL")
    
    # Backup Configuration
    backup_enabled: bool = True
    backup_full_schedule_cron: str = "0 2 * * *"  # Daily at 2 AM
    backup_retention_days: int = 90
    backup_git_enabled: bool = False
    backup_git_repo_url: str | None = None
    backup_git_branch: str = "main"
    backup_git_author_name: str = "Mist Automation"
    backup_git_author_email: str = "automation@example.com"
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # json or text
    log_file: str | None = None

    # External Integrations
    slack_webhook_url: str | None = None
    servicenow_instance_url: str | None = None
    servicenow_username: str | None = None
    servicenow_password: str | None = None
    pagerduty_integration_key: str | None = None

    # SMTP Email Configuration
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "noreply@example.com"
    smtp_use_tls: bool = True
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v):
        """Validate environment value."""
        allowed = ["development", "staging", "production"]
        if v not in allowed:
            raise ValueError(f"Environment must be one of {allowed}")
        return v
    
    @field_validator("mist_cloud_region")
    @classmethod
    def validate_mist_region(cls, v):
        """Validate Mist cloud region."""
        allowed = ["global", "eu", "apac"]
        if v not in allowed:
            raise ValueError(f"Mist cloud region must be one of {allowed}")
        return v
    
    @property
    def mongodb_connection_url(self) -> str:
        """Get MongoDB connection URL with credentials if configured."""
        if self.mongodb_username:
            from urllib.parse import urlparse, urlunparse, quote_plus
            parsed = urlparse(self.mongodb_url)
            username = quote_plus(self.mongodb_username)
            password = quote_plus(self.mongodb_password or "")
            netloc = f"{username}:{password}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
        return self.mongodb_url

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"
    
    @property
    def mongodb_connection_kwargs(self) -> dict:
        """Get MongoDB connection kwargs."""
        return {
            "minPoolSize": self.mongodb_min_pool_size,
            "maxPoolSize": self.mongodb_max_pool_size,
        }


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    This ensures settings are loaded only once and reused across the application.
    """
    return Settings()


# Convenience export
settings = get_settings()

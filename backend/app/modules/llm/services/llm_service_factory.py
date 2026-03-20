"""
Shared factory for creating an LLMService from system config.
"""

import structlog

from app.core.exceptions import ConfigurationError

logger = structlog.get_logger(__name__)


async def create_llm_service():
    """Get SystemConfig, decrypt API key, create LLMService.

    Raises ConfigurationError if LLM is not configured.
    """
    from app.core.security import decrypt_sensitive_data
    from app.models.system import SystemConfig
    from app.modules.llm.services.llm_service import LLMService

    config = await SystemConfig.get_config()

    if not config.llm_enabled:
        raise ConfigurationError("LLM integration is not enabled")
    if not config.llm_provider:
        raise ConfigurationError("LLM provider is not configured")
    if not config.llm_api_key:
        raise ConfigurationError("LLM API key is not configured")

    try:
        api_key = decrypt_sensitive_data(config.llm_api_key)
    except Exception as e:
        logger.warning("llm_api_key_decryption_failed", error=str(e))
        raise ConfigurationError("Failed to decrypt LLM API key") from e

    base_url = config.llm_base_url
    # LM Studio defaults to http://localhost:1234/v1 if no base URL set
    if config.llm_provider == "lm_studio" and not base_url:
        base_url = "http://localhost:1234/v1"

    return LLMService(
        provider=config.llm_provider,
        api_key=api_key,
        model=config.llm_model or _default_model(config.llm_provider),
        base_url=base_url,
        temperature=config.llm_temperature,
        max_tokens=config.llm_max_tokens_per_request,
    )


async def is_llm_available() -> bool:
    """Check if LLM is configured without raising."""
    from app.models.system import SystemConfig

    try:
        config = await SystemConfig.get_config()
        return bool(config.llm_enabled and config.llm_provider and config.llm_api_key)
    except Exception:
        return False


def _default_model(provider: str) -> str:
    """Return a sensible default model for a given provider."""
    defaults = {
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-20250514",
        "ollama": "llama3.1",
        "lm_studio": "local-model",
        "azure_openai": "gpt-4o",
        "bedrock": "anthropic.claude-sonnet-4-20250514-v1:0",
    }
    return defaults.get(provider, "gpt-4o")

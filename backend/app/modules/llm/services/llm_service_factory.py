"""
Shared factory for creating an LLMService from a named LLMConfig.
"""

import structlog
from beanie import PydanticObjectId

from app.core.exceptions import ConfigurationError

logger = structlog.get_logger(__name__)

_LOCAL_PROVIDERS = {"lm_studio", "ollama"}


async def create_llm_service(config_id: str | None = None):
    """Create an LLMService from a named LLMConfig.

    If ``config_id`` is provided, loads that specific config.
    Otherwise, loads the default config (``is_default=True``).

    Raises ConfigurationError if LLM is not configured or the config is not found.
    """
    from app.core.security import decrypt_sensitive_data
    from app.models.system import SystemConfig
    from app.modules.llm.models import LLMConfig
    from app.modules.llm.services.llm_service import LLMService

    # Global kill switch
    sys_config = await SystemConfig.get_config()
    if not sys_config.llm_enabled:
        raise ConfigurationError("LLM integration is not enabled")

    # Load config
    if config_id:
        try:
            llm_config = await LLMConfig.get(PydanticObjectId(config_id))
        except Exception as exc:
            raise ConfigurationError("Invalid LLM config ID") from exc
        if not llm_config:
            raise ConfigurationError("LLM config not found")
    else:
        llm_config = await LLMConfig.find_one(LLMConfig.is_default == True, LLMConfig.enabled == True)  # noqa: E712
        if not llm_config:
            raise ConfigurationError("No default LLM config found")

    if not llm_config.enabled:
        raise ConfigurationError(f"LLM config '{llm_config.name}' is disabled")
    if not llm_config.api_key:
        raise ConfigurationError(f"LLM config '{llm_config.name}' has no API key")

    try:
        api_key = decrypt_sensitive_data(llm_config.api_key)
    except Exception as e:
        logger.warning("llm_api_key_decryption_failed", config=llm_config.name, error=str(e))
        raise ConfigurationError("Failed to decrypt LLM API key") from e

    base_url = llm_config.base_url
    if llm_config.provider == "lm_studio" and not base_url:
        base_url = "http://localhost:1234/v1"

    # SSRF check — skip for local providers
    if base_url and llm_config.provider not in _LOCAL_PROVIDERS:
        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(base_url)

    return LLMService(
        provider=llm_config.provider,
        api_key=api_key,
        model=llm_config.model or _default_model(llm_config.provider),
        base_url=base_url,
        temperature=llm_config.temperature,
        max_tokens=llm_config.max_tokens_per_request,
    )


async def is_llm_available() -> bool:
    """Check if LLM is configured without raising."""
    from app.models.system import SystemConfig
    from app.modules.llm.models import LLMConfig

    try:
        sys_config = await SystemConfig.get_config()
        if not sys_config.llm_enabled:
            return False
        default = await LLMConfig.find_one(LLMConfig.is_default == True, LLMConfig.enabled == True)  # noqa: E712
        return default is not None and bool(default.api_key)
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
        "vertex": "gemini-2.0-flash",
    }
    return defaults.get(provider, "gpt-4o")

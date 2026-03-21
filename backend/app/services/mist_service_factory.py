"""
Shared factory for creating a MistService from system config with env fallback.

Caches resolved config (decrypted token, cloud region, org_id) for a short TTL
to avoid hitting MongoDB on every instantiation.
"""

import time

import structlog

from app.config import settings
from app.services.mist_service import MistService

logger = structlog.get_logger(__name__)

# In-memory config cache with TTL
_config_cache: dict | None = None
_config_cache_time: float = 0
_CONFIG_CACHE_TTL = 30  # seconds


def invalidate_mist_config_cache() -> None:
    """Force the next create_mist_service() call to re-read SystemConfig."""
    global _config_cache, _config_cache_time
    _config_cache = None
    _config_cache_time = 0


async def _get_resolved_config() -> dict:
    """Fetch and cache the resolved Mist config (token, org_id, region)."""
    global _config_cache, _config_cache_time

    now = time.monotonic()
    if _config_cache and (now - _config_cache_time) < _CONFIG_CACHE_TTL:
        return _config_cache

    from app.core.security import decrypt_sensitive_data
    from app.models.system import SystemConfig

    config = await SystemConfig.get_config()
    api_token = settings.mist_api_token
    if config and config.mist_api_token:
        try:
            api_token = decrypt_sensitive_data(config.mist_api_token)
        except Exception as e:
            logger.warning("mist_token_decryption_failed", error=str(e))

    resolved = {
        "api_token": api_token,
        "org_id": (config.mist_org_id if config else None) or settings.mist_org_id,
        "cloud_region": (config.mist_cloud_region if config else None) or "global_01",
    }
    _config_cache = resolved
    _config_cache_time = now
    return resolved


async def create_mist_service(org_id: str | None = None) -> MistService:
    """Get SystemConfig, decrypt token, create MistService with env fallback."""
    resolved = await _get_resolved_config()

    return MistService(
        api_token=resolved["api_token"],
        org_id=org_id or resolved["org_id"],
        cloud_region=resolved["cloud_region"],
    )

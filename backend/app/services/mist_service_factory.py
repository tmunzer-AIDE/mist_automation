"""
Shared factory for creating a MistService from system config with env fallback.
"""

import structlog

from app.config import settings
from app.services.mist_service import MistService

logger = structlog.get_logger(__name__)


async def create_mist_service(org_id: str | None = None) -> MistService:
    """Get SystemConfig, decrypt token, create MistService with env fallback."""
    from app.core.security import decrypt_sensitive_data
    from app.models.system import SystemConfig

    config = await SystemConfig.get_config()
    api_token = settings.mist_api_token
    if config and config.mist_api_token:
        try:
            api_token = decrypt_sensitive_data(config.mist_api_token)
        except Exception as e:
            logger.warning("mist_token_decryption_failed", error=str(e))
    cloud_region = (config.mist_cloud_region if config else None) or "global_01"

    return MistService(
        api_token=api_token,
        org_id=org_id or (config.mist_org_id if config else None) or settings.mist_org_id,
        cloud_region=cloud_region,
    )

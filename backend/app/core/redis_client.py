"""
Redis client utilities for WebAuthn challenge storage.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_CHALLENGE_PREFIX = "webauthn:challenge:"
_CHALLENGE_TTL = 300  # 5 minutes


class WebAuthnChallengeStore:
    """
    Store and retrieve WebAuthn challenges.
    Uses Redis when available, falls back to an in-memory dict for testing.
    Challenges are single-use: retrieved once then deleted.
    """

    def __init__(self, redis: Any | None = None) -> None:
        self._redis = redis
        self._fallback: dict[str, str] = {}

    @staticmethod
    def generate_session_id() -> str:
        return uuid.uuid4().hex

    async def store_challenge(self, session_id: str, data: dict) -> None:
        key = f"{_CHALLENGE_PREFIX}{session_id}"
        payload = json.dumps(data)
        if self._redis is not None:
            await self._redis.set(key, payload, ex=_CHALLENGE_TTL)
        else:
            self._fallback[key] = payload

    async def get_challenge(self, session_id: str) -> dict | None:
        key = f"{_CHALLENGE_PREFIX}{session_id}"
        if self._redis is not None:
            payload = await self._redis.get(key)
            if payload is None:
                return None
            await self._redis.delete(key)
            return json.loads(payload)
        else:
            payload = self._fallback.pop(key, None)
            if payload is None:
                return None
            return json.loads(payload)


_store: WebAuthnChallengeStore | None = None


async def get_challenge_store() -> WebAuthnChallengeStore:
    """Get or create the singleton challenge store."""
    global _store
    if _store is None:
        try:
            from redis.asyncio import from_url

            from app.config import settings

            redis = from_url(settings.redis_url, decode_responses=True)
            _store = WebAuthnChallengeStore(redis=redis)
            logger.info("webauthn_challenge_store_initialized", backend="redis")
        except Exception:
            logger.warning("webauthn_challenge_store_fallback", backend="memory")
            _store = WebAuthnChallengeStore(redis=None)
    return _store

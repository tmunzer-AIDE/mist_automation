"""One-time migration: rename TwinSession.source from 'llm_chat' to 'mcp'.

Context: the ``source`` Literal on ``TwinSession`` was renamed from ``"llm_chat"``
to ``"mcp"`` (to reflect that the digital twin is now driven by MCP clients,
not a single LLM chat surface). Existing Mongo documents with
``source == "llm_chat"`` are now rejected by Pydantic on load, so they must be
migrated in place.

Run manually::

    cd backend && python -m migrations.20260412_rename_llm_chat_to_mcp

Idempotent: subsequent runs match zero documents and are a no-op.

Why the raw Motor collection? Beanie's ``find(...).update({...})`` ORM path
materialises documents through Pydantic first, which will FAIL on legacy
``source="llm_chat"`` rows because the Literal no longer accepts that value.
``TwinSession.get_motor_collection().update_many(...)`` bypasses Pydantic and
issues a raw Mongo update, which is exactly what we want here.
"""

import asyncio

import structlog

from app.core.database import Database
from app.modules.digital_twin.models import TwinSession

logger = structlog.get_logger(__name__)


async def main() -> None:
    await Database.connect_db()
    try:
        collection = TwinSession.get_motor_collection()
        result = await collection.update_many(
            {"source": "llm_chat"},
            {"$set": {"source": "mcp"}},
        )
        logger.info(
            "twin_source_migration_done",
            matched=result.matched_count,
            modified=result.modified_count,
        )
    finally:
        await Database.close_db()


if __name__ == "__main__":
    asyncio.run(main())

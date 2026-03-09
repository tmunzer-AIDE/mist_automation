"""
One-time migration: backfill the ``references`` field on existing BackupObject
documents by running ``extract_references()`` over each document's configuration.

Usage:
    python -m app.modules.backup.migrations.backfill_references
"""

import asyncio
import structlog

from app.modules.backup.reference_map import REFERENCE_MAP, extract_references

logger = structlog.get_logger(__name__)


async def backfill() -> dict[str, int]:
    """Backfill references for all BackupObject documents whose type is in REFERENCE_MAP."""
    from app.core.database import Database
    await Database.connect_db()

    from app.modules.backup.models import BackupObject, ObjectReference

    updated = 0
    skipped = 0
    total = 0

    eligible_types = list(REFERENCE_MAP.keys())

    cursor = BackupObject.find({"object_type": {"$in": eligible_types}})
    async for doc in cursor:
        total += 1
        refs_raw = extract_references(doc.object_type, doc.configuration)
        refs = [ObjectReference(**r) for r in refs_raw]

        if refs == doc.references:
            skipped += 1
            continue

        doc.references = refs
        await doc.save()
        updated += 1

    stats = {"total": total, "updated": updated, "skipped": skipped}
    logger.info("backfill_references_complete", **stats)
    return stats


if __name__ == "__main__":
    asyncio.run(backfill())

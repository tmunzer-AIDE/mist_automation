#!/usr/bin/env python3
"""
One-time migration script: fix duplicate (object_id, version) pairs in backup_objects.

For each object_id, renumbers all versions sequentially (1, 2, 3, ...) ordered by
backed_up_at ascending, and rebuilds the previous_version_id chain.

Run from the backend directory:
    python scripts/fix_duplicate_versions.py

Safe to run multiple times — idempotent (already-sequential versions are unchanged).
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.config import settings

    client = AsyncIOMotorClient(settings.mongodb_connection_url)
    db = client[settings.mongodb_db_name]
    collection = db["backup_objects"]

    # Drop the unique index if it exists (it failed to create due to duplicates)
    try:
        await collection.drop_index("unique_object_version")
        print("Dropped existing unique_object_version index.")
    except Exception:
        print("No existing unique_object_version index to drop.")

    # Get all distinct object_ids
    object_ids = await collection.distinct("object_id")
    print(f"Found {len(object_ids)} distinct objects to process.")

    fixed_objects = 0
    fixed_versions = 0

    for i, object_id in enumerate(object_ids):
        # Get all versions for this object, sorted by backed_up_at ascending
        cursor = collection.find({"object_id": object_id}).sort("backed_up_at", 1)
        docs = await cursor.to_list(length=None)

        if not docs:
            continue

        # Check if already sequential
        versions = [d["version"] for d in docs]
        expected = list(range(1, len(docs) + 1))
        if versions == expected:
            # Check previous_version_id chain is correct too
            chain_ok = True
            for j, doc in enumerate(docs):
                expected_prev = docs[j - 1]["_id"] if j > 0 else None
                if doc.get("previous_version_id") != expected_prev:
                    chain_ok = False
                    break
            if chain_ok:
                continue

        # Renumber sequentially and rebuild chain
        fixed_objects += 1
        prev_id = None
        for j, doc in enumerate(docs):
            new_version = j + 1
            update = {}

            if doc["version"] != new_version:
                update["version"] = new_version
                fixed_versions += 1

            if doc.get("previous_version_id") != prev_id:
                update["previous_version_id"] = prev_id

            if update:
                await collection.update_one({"_id": doc["_id"]}, {"$set": update})

            prev_id = doc["_id"]

        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(object_ids)} objects...")

    print(f"\nDone. Fixed {fixed_objects} objects, renumbered {fixed_versions} version records.")

    # Now create the unique index
    from pymongo import IndexModel

    try:
        await collection.create_indexes(
            [IndexModel([("object_id", 1), ("version", 1)], unique=True, name="unique_object_version")]
        )
        print("Created unique_object_version index successfully.")
    except Exception as e:
        print(f"ERROR creating index: {e}")
        print("There may still be duplicates. Check the output above.")
        sys.exit(1)

    client.close()
    print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(main())

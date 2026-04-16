#!/usr/bin/env python3
"""One-time repair script for skewed backup timestamps.

This fixes historical corruption where an older non-latest version's ``backed_up_at``
was updated after the object had already been deleted in a newer version.

Repair rule:
- For each object whose latest version is deleted,
- Clamp earlier versions where ``backed_up_at > latest.backed_up_at``
  to ``latest.backed_up_at``.

Dry-run by default. Use ``--apply`` to persist changes.

Run from backend directory:
    .venv/bin/python scripts/repair_deleted_backup_timestamps.py
    .venv/bin/python scripts/repair_deleted_backup_timestamps.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import UpdateMany

# Add backend to path so script can import app modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair skewed backed_up_at values for deleted backup chains")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist fixes. Without this flag, the script only reports what would change.",
    )
    parser.add_argument(
        "--org-id",
        default="",
        help="Optional org_id filter. When omitted, scans all organizations.",
    )
    parser.add_argument(
        "--object-id",
        action="append",
        default=[],
        help="Optional object_id filter. May be provided multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of skewed objects to process (0 = no limit).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Bulk update batch size when --apply is set.",
    )
    return parser.parse_args()


def _fmt_dt(value: Any) -> str:
    if not isinstance(value, datetime):
        return "<invalid>"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def _latest_deleted_cursor(collection, org_id: str, object_ids: list[str]):
    match: dict[str, Any] = {}
    if org_id:
        match["org_id"] = org_id
    if object_ids:
        match["object_id"] = {"$in": object_ids}

    pipeline: list[dict[str, Any]] = []
    if match:
        pipeline.append({"$match": match})

    pipeline.extend(
        [
            {"$sort": {"object_id": 1, "version": -1}},
            {
                "$group": {
                    "_id": "$object_id",
                    "org_id": {"$first": "$org_id"},
                    "latest_version": {"$first": "$version"},
                    "latest_doc_id": {"$first": "$_id"},
                    "latest_is_deleted": {"$first": "$is_deleted"},
                    "latest_backed_up_at": {"$first": "$backed_up_at"},
                }
            },
            {"$match": {"latest_is_deleted": True}},
        ]
    )

    return collection.aggregate(pipeline)


async def main() -> None:
    args = _parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient

    from app.config import settings

    client = AsyncIOMotorClient(settings.mongodb_connection_url)
    db = client[settings.mongodb_db_name]
    collection = db["backup_objects"]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] Scanning for skewed deleted backup chains...")

    latest_deleted = _latest_deleted_cursor(collection, args.org_id.strip(), args.object_id)

    skewed_objects = 0
    candidate_updates: list[UpdateMany] = []
    docs_to_fix = 0
    processed = 0

    latest_deleted_count = 0

    async for row in latest_deleted:
        latest_deleted_count += 1
        obj_id = row["_id"]
        latest_ver = row.get("latest_version")
        cap_time = row.get("latest_backed_up_at")

        if not isinstance(latest_ver, int) or latest_ver <= 1:
            continue
        if not isinstance(cap_time, datetime):
            print(f"[WARN] Skipping {obj_id}: latest_backed_up_at is not a datetime")
            continue

        query = {
            "object_id": obj_id,
            "version": {"$lt": latest_ver},
            "backed_up_at": {"$gt": cap_time},
        }

        count = await collection.count_documents(query)
        if count == 0:
            continue

        skewed_objects += 1
        docs_to_fix += count
        processed += 1

        print(
            f"[SKEW] object_id={obj_id} latest=v{latest_ver} deleted_at={_fmt_dt(cap_time)} "
            f"affected_docs={count}"
        )

        if args.apply:
            candidate_updates.append(UpdateMany(query, {"$set": {"backed_up_at": cap_time}}, upsert=False))

        if args.limit > 0 and processed >= args.limit:
            print(f"Reached --limit ({args.limit}); stopping early.")
            break

    print(f"Found {latest_deleted_count} objects with latest version marked deleted.")

    if not args.apply:
        print(
            f"[DRY-RUN] Done. Skewed objects={skewed_objects}, affected documents={docs_to_fix}. "
            "Re-run with --apply to persist changes."
        )
        client.close()
        return

    if not candidate_updates:
        print("[APPLY] No updates required.")
        client.close()
        return

    modified_total = 0
    for i in range(0, len(candidate_updates), max(1, args.batch_size)):
        batch = candidate_updates[i : i + max(1, args.batch_size)]
        result = await collection.bulk_write(batch, ordered=False)
        modified_total += result.modified_count

    print(
        f"[APPLY] Completed. Skewed objects={skewed_objects}, "
        f"candidate docs={docs_to_fix}, modified docs={modified_total}."
    )

    client.close()


if __name__ == "__main__":
    asyncio.run(main())

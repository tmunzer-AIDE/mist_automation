"""
Dashboard API endpoint — role-aware stats, activity trends, and recent events.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends

from app.dependencies import get_current_user_from_token
from app.models.user import User
from app.modules.automation.models.execution import WorkflowExecution
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.automation.models.workflow import Workflow
from app.modules.backup.models import BackupJob
from app.modules.reports.models import ReportJob

router = APIRouter()
logger = structlog.get_logger(__name__)

ACTIVITY_DAYS = 14
STATS_WINDOW_DAYS = 7
HIGHLIGHT_HOURS = 24
RECENT_LIMIT = 10
RECENT_PER_MODULE = 5


def _fill_missing_days(data: dict[str, dict], days: int) -> list[str]:
    """Return sorted list of date strings for the last N days, filling gaps."""
    today = datetime.now(timezone.utc).date()
    all_dates = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    for d in all_dates:
        data.setdefault(d, {})
    return all_dates


from app.utils.db_helpers import facet_counts as _facet_counts


async def _windowed_facet_counts(
    model, field: str, values: list[str], date_field: str, cutoff: datetime, extra_match: dict | None = None
) -> dict[str, int]:
    """Run a $facet aggregation with a time-window filter."""
    match_filter: dict = {date_field: {"$gte": cutoff}}
    if extra_match:
        match_filter.update(extra_match)
    facets: dict = {"total": [{"$count": "n"}]}
    for v in values:
        facets[v] = [{"$match": {field: v}}, {"$count": "n"}]
    results = await model.aggregate([{"$match": match_filter}, {"$facet": facets}]).to_list()
    row = results[0] if results else {}
    out: dict[str, int] = {}
    for key in ["total"] + values:
        bucket = row.get(key, [])
        out[key] = bucket[0]["n"] if bucket else 0
    return out


async def _windowed_webhook_facet(cutoff: datetime) -> dict[str, int]:
    """Webhook counts within a time window."""
    results = await WebhookEvent.aggregate(
        [
            {"$match": {"received_at": {"$gte": cutoff}}},
            {
                "$facet": {
                    "total": [{"$count": "n"}],
                    "processed": [{"$match": {"processed": True}}, {"$count": "n"}],
                    "pending": [{"$match": {"processed": False}}, {"$count": "n"}],
                }
            },
        ]
    ).to_list()
    row = results[0] if results else {}

    def _get(key: str) -> int:
        bucket = row.get(key, [])
        return bucket[0]["n"] if bucket else 0

    return {"total": _get("total"), "processed": _get("processed"), "pending": _get("pending")}


async def _webhook_facet() -> dict[str, int]:
    """Webhook counts (boolean processed field needs dedicated facet)."""
    results = await WebhookEvent.aggregate(
        [
            {
                "$facet": {
                    "total": [{"$count": "n"}],
                    "processed": [{"$match": {"processed": True}}, {"$count": "n"}],
                    "pending": [{"$match": {"processed": False}}, {"$count": "n"}],
                }
            }
        ]
    ).to_list()
    row = results[0] if results else {}

    def _get(key: str) -> int:
        bucket = row.get(key, [])
        return bucket[0]["n"] if bucket else 0

    return {"total": _get("total"), "processed": _get("processed"), "pending": _get("pending")}


async def _user_facet() -> dict[str, int]:
    """User counts by active/admin status."""
    from app.models.user import User as UserModel

    results = await UserModel.aggregate(
        [
            {
                "$facet": {
                    "total": [{"$count": "n"}],
                    "active": [{"$match": {"is_active": True}}, {"$count": "n"}],
                    "admins": [{"$match": {"roles": "admin"}}, {"$count": "n"}],
                }
            }
        ]
    ).to_list()
    row = results[0] if results else {}

    def _get(key: str) -> int:
        bucket = row.get(key, [])
        return bucket[0]["n"] if bucket else 0

    return {"total": _get("total"), "active": _get("active"), "admins": _get("admins")}


# ── Time-series helpers ──────────────────────────────────────────────────


async def _execution_activity(cutoff: datetime) -> dict[str, dict]:
    """Daily execution succeeded/failed counts."""
    pipeline = [
        {"$match": {"started_at": {"$gte": cutoff}, "is_simulation": False}},
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$started_at"}},
                "succeeded": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$in": ["$status", ["failed", "timeout"]]}, 1, 0]}},
            }
        },
    ]
    results = await WorkflowExecution.aggregate(pipeline).to_list()
    return {r["_id"]: {"succeeded": r["succeeded"], "failed": r["failed"]} for r in results}


async def _backup_activity(cutoff: datetime) -> dict[str, dict]:
    """Daily backup completed/failed counts."""
    pipeline = [
        {"$match": {"created_at": {"$gte": cutoff}}},
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
                "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            }
        },
    ]
    results = await BackupJob.aggregate(pipeline).to_list()
    return {r["_id"]: {"completed": r["completed"], "failed": r["failed"]} for r in results}


async def _webhook_activity(cutoff: datetime) -> dict[str, dict]:
    """Daily webhook received counts."""
    pipeline = [
        {"$match": {"received_at": {"$gte": cutoff}}},
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$received_at"}},
                "received": {"$sum": 1},
            }
        },
    ]
    results = await WebhookEvent.aggregate(pipeline).to_list()
    return {r["_id"]: {"received": r["received"]} for r in results}


# ── Recent activity helpers ──────────────────────────────────────────────


async def _recent_executions() -> list[dict]:
    """Most recent completed/failed executions."""
    execs = await WorkflowExecution.aggregate(
        [
            {"$match": {"status": {"$in": ["success", "failed", "timeout", "partial"]}, "is_simulation": False}},
            {"$sort": {"completed_at": -1}},
            {"$limit": RECENT_PER_MODULE},
            {
                "$project": {
                    "_id": 1,
                    "workflow_name": 1,
                    "status": 1,
                    "completed_at": 1,
                    "duration_ms": 1,
                    "nodes_executed": 1,
                }
            },
        ]
    ).to_list()
    items = []
    for ex in execs:
        dur = ex.get("duration_ms")
        detail = f"{ex.get('nodes_executed', 0)} nodes"
        if dur is not None:
            detail += f", {dur / 1000:.1f}s"
        status = ex.get("status", "")
        if status == "success":
            status = "succeeded"
        items.append(
            {
                "type": "execution",
                "id": str(ex["_id"]),
                "title": ex.get("workflow_name", "Workflow"),
                "status": status,
                "timestamp": ex.get("completed_at"),
                "detail": detail,
            }
        )
    return items


async def _recent_backups() -> list[dict]:
    """Most recent completed/failed backups."""
    jobs = await BackupJob.aggregate(
        [
            {"$match": {"status": {"$in": ["completed", "failed"]}}},
            {"$sort": {"completed_at": -1}},
            {"$limit": RECENT_PER_MODULE},
            {"$project": {"_id": 1, "backup_type": 1, "status": 1, "completed_at": 1, "object_count": 1}},
        ]
    ).to_list()
    items = []
    for job in jobs:
        label = (job.get("backup_type") or "full").replace("_", " ").title() + " backup"
        obj_count = job.get("object_count", 0)
        detail = f"{obj_count} object{'s' if obj_count != 1 else ''}" if obj_count else None
        items.append(
            {
                "type": "backup",
                "id": str(job["_id"]),
                "title": label,
                "status": job.get("status", ""),
                "timestamp": job.get("completed_at"),
                "detail": detail,
            }
        )
    return items


async def _recent_reports() -> list[dict]:
    """Most recent completed/failed reports."""
    reports = await ReportJob.aggregate(
        [
            {"$match": {"status": {"$in": ["completed", "failed"]}}},
            {"$sort": {"completed_at": -1}},
            {"$limit": RECENT_PER_MODULE},
            {"$project": {"_id": 1, "site_name": 1, "status": 1, "completed_at": 1, "report_type": 1}},
        ]
    ).to_list()
    items = []
    for rpt in reports:
        site = rpt.get("site_name") or "Unknown site"
        items.append(
            {
                "type": "report",
                "id": str(rpt["_id"]),
                "title": f"Validation — {site}",
                "status": rpt.get("status", ""),
                "timestamp": rpt.get("completed_at"),
                "detail": None,
            }
        )
    return items


# ── Highlights ─────────────────────────────────────────────────────────


async def _build_highlights(
    has_automation: bool, has_backup: bool, has_reports: bool
) -> list[dict]:
    """Build role-specific alert highlights for the last 24 hours."""
    highlight_cutoff = datetime.now(timezone.utc) - timedelta(hours=HIGHLIGHT_HOURS)
    tasks: dict[str, asyncio.Task] = {}

    if has_automation:
        tasks["failed_exec"] = asyncio.ensure_future(
            WorkflowExecution.find(
                {"status": {"$in": ["failed", "timeout"]}, "started_at": {"$gte": highlight_cutoff}, "is_simulation": False}
            ).count()
        )
        tasks["stuck_exec"] = asyncio.ensure_future(
            WorkflowExecution.find(
                {"status": "running", "started_at": {"$lte": highlight_cutoff}}
            ).count()
        )
    if has_backup:
        tasks["failed_backup"] = asyncio.ensure_future(
            BackupJob.find({"status": "failed", "created_at": {"$gte": highlight_cutoff}}).count()
        )
    if has_reports:
        tasks["failed_report"] = asyncio.ensure_future(
            ReportJob.find({"status": "failed", "created_at": {"$gte": highlight_cutoff}}).count()
        )

    if tasks:
        await asyncio.gather(*tasks.values())

    results = {k: t.result() for k, t in tasks.items()}
    highlights: list[dict] = []

    if results.get("failed_exec", 0) > 0:
        n = results["failed_exec"]
        highlights.append(
            {
                "level": "error",
                "icon": "error",
                "message": f"{n} workflow execution{'s' if n != 1 else ''} failed in the last 24h",
                "route": "/workflows/executions",
                "count": n,
            }
        )
    if results.get("stuck_exec", 0) > 0:
        n = results["stuck_exec"]
        highlights.append(
            {
                "level": "warning",
                "icon": "hourglass_top",
                "message": f"{n} execution{'s' if n != 1 else ''} stuck running for over 24h",
                "route": "/workflows/executions",
                "count": n,
            }
        )
    if results.get("failed_backup", 0) > 0:
        n = results["failed_backup"]
        highlights.append(
            {
                "level": "error",
                "icon": "cloud_off",
                "message": f"{n} backup{'s' if n != 1 else ''} failed in the last 24h",
                "route": "/backup",
                "count": n,
            }
        )
    if results.get("failed_report", 0) > 0:
        n = results["failed_report"]
        highlights.append(
            {
                "level": "warning",
                "icon": "assignment_late",
                "message": f"{n} report{'s' if n != 1 else ''} failed in the last 24h",
                "route": "/reports",
                "count": n,
            }
        )

    return highlights


# ── Main endpoint ────────────────────────────────────────────────────────


@router.get("/dashboard/stats", tags=["Dashboard"])
async def get_dashboard_stats(current_user: User = Depends(get_current_user_from_token)):
    """
    Role-aware dashboard statistics.

    Returns summary counts, 14-day activity time-series, and recent events.
    Each section is only present if the user has the matching role.
    """
    has_admin = current_user.is_admin()
    has_automation = current_user.can_manage_workflows()
    has_backup = current_user.can_manage_backups()
    has_reports = current_user.can_manage_post_deployment()

    cutoff = datetime.now(timezone.utc) - timedelta(days=ACTIVITY_DAYS)
    stats_cutoff = datetime.now(timezone.utc) - timedelta(days=STATS_WINDOW_DAYS)

    # ── Gather all queries in parallel ────────────────────────────────
    tasks: dict[str, asyncio.Task] = {}

    if has_admin:
        tasks["users"] = asyncio.ensure_future(_user_facet())

    if has_automation:
        tasks["workflows"] = asyncio.ensure_future(_facet_counts(Workflow, "status", ["enabled", "draft"]))
        tasks["executions"] = asyncio.ensure_future(
            _windowed_facet_counts(
                WorkflowExecution, "status", ["pending", "running", "success", "failed"],
                "started_at", stats_cutoff, extra_match={"is_simulation": False},
            )
        )
        tasks["webhooks"] = asyncio.ensure_future(_windowed_webhook_facet(stats_cutoff))
        tasks["exec_activity"] = asyncio.ensure_future(_execution_activity(cutoff))
        tasks["webhook_activity"] = asyncio.ensure_future(_webhook_activity(cutoff))
        tasks["recent_exec"] = asyncio.ensure_future(_recent_executions())

    if has_backup:
        tasks["backups"] = asyncio.ensure_future(
            _windowed_facet_counts(BackupJob, "status", ["completed", "pending", "failed"], "created_at", stats_cutoff)
        )
        tasks["backup_activity"] = asyncio.ensure_future(_backup_activity(cutoff))
        tasks["recent_backup"] = asyncio.ensure_future(_recent_backups())

    if has_reports:
        tasks["reports"] = asyncio.ensure_future(
            _windowed_facet_counts(ReportJob, "status", ["completed", "pending", "failed"], "created_at", stats_cutoff)
        )
        tasks["recent_report"] = asyncio.ensure_future(_recent_reports())

    tasks["highlights"] = asyncio.ensure_future(_build_highlights(has_automation, has_backup, has_reports))

    if tasks:
        await asyncio.gather(*tasks.values())

    results = {k: t.result() for k, t in tasks.items()}

    # ── Build response ────────────────────────────────────────────────
    response: dict = {
        "display_name": current_user.display_name(),
        "stats_window_days": STATS_WINDOW_DAYS,
    }

    highlights = results.get("highlights", [])
    if highlights:
        response["highlights"] = highlights

    if has_admin:
        response["users"] = results["users"]

    if has_automation:
        ex_counts = results["executions"]
        response["workflows"] = results["workflows"]
        response["executions"] = {
            "total": ex_counts["total"],
            "succeeded": ex_counts.get("success", 0),
            "failed": ex_counts.get("failed", 0),
            "running": ex_counts.get("running", 0),
        }
        response["webhooks"] = results["webhooks"]

    if has_backup:
        response["backups"] = results["backups"]

    if has_reports:
        response["reports"] = results["reports"]

    # ── Activity time-series ──────────────────────────────────────────
    activity: dict = {}
    has_any_activity = False

    if has_automation:
        exec_data = results.get("exec_activity", {})
        _fill_missing_days(exec_data, ACTIVITY_DAYS)
        all_dates = sorted(exec_data.keys())
        activity["labels"] = [d[5:] for d in all_dates]
        activity["executions"] = {
            "succeeded": [exec_data[d].get("succeeded", 0) for d in all_dates],
            "failed": [exec_data[d].get("failed", 0) for d in all_dates],
        }
        wh_data = results.get("webhook_activity", {})
        _fill_missing_days(wh_data, ACTIVITY_DAYS)
        activity["webhooks"] = {
            "received": [wh_data[d].get("received", 0) for d in sorted(wh_data.keys())],
        }
        has_any_activity = True

    if has_backup:
        bk_data = results.get("backup_activity", {})
        _fill_missing_days(bk_data, ACTIVITY_DAYS)
        all_dates_bk = sorted(bk_data.keys())
        if "labels" not in activity:
            activity["labels"] = [d[5:] for d in all_dates_bk]
        activity["backups"] = {
            "completed": [bk_data[d].get("completed", 0) for d in all_dates_bk],
            "failed": [bk_data[d].get("failed", 0) for d in all_dates_bk],
        }
        has_any_activity = True

    if has_any_activity:
        response["activity"] = activity

    # ── Recent activity ───────────────────────────────────────────────
    recent_items: list[dict] = []
    if has_automation:
        recent_items.extend(results.get("recent_exec", []))
    if has_backup:
        recent_items.extend(results.get("recent_backup", []))
    if has_reports:
        recent_items.extend(results.get("recent_report", []))

    if recent_items:
        _epoch = datetime(1970, 1, 1)

        def _sort_ts(item: dict) -> datetime:
            ts = item.get("timestamp") or _epoch
            # Motor may return naive datetimes; strip tzinfo for consistent comparison
            return ts.replace(tzinfo=None) if hasattr(ts, "replace") else _epoch

        recent_items.sort(key=_sort_ts, reverse=True)
        response["recent"] = recent_items[:RECENT_LIMIT]

    return response

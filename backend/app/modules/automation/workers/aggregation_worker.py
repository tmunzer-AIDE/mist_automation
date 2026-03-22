"""
Aggregation worker — buffers webhook events into time windows
and fires aggregated triggers when the window closes.
"""

from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.triggers.date import DateTrigger
from beanie import PydanticObjectId

from app.core.tasks import create_background_task
from app.modules.automation.models.aggregation import AggregationWindow
from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.automation.models.workflow import Workflow, WorkflowStatus
from app.modules.automation.services.executor_service import WorkflowExecutor
from app.modules.automation.workers.scheduler import get_scheduler

logger = structlog.get_logger(__name__)


async def _broadcast_window_update(window, msg_type: str = "aggregation_updated") -> None:
    """Broadcast aggregation window status change via WebSocket."""
    try:
        from app.core.websocket import ws_manager

        await ws_manager.broadcast(
            f"workflow:{window.workflow_id}:aggregation",
            {
                "type": msg_type,
                "data": {
                    "window_id": str(window.id) if hasattr(window, "id") else str(window.get("_id", "")),
                    "workflow_id": str(window.workflow_id) if hasattr(window, "workflow_id") else str(window.get("workflow_id", "")),
                    "group_key": window.group_key if hasattr(window, "group_key") else "",
                    "status": window.status if hasattr(window, "status") else "collecting",
                    "event_count": window.event_count if hasattr(window, "event_count") else 0,
                    "site_id": window.site_id if hasattr(window, "site_id") else None,
                    "site_name": window.site_name if hasattr(window, "site_name") else None,
                    "window_end": window.window_end.isoformat() if hasattr(window, "window_end") and window.window_end else "",
                    "window_seconds": window.window_seconds if hasattr(window, "window_seconds") else 0,
                },
            },
        )
    except Exception as e:
        logger.debug("ws_broadcast_failed", error=str(e))


async def buffer_event_for_aggregation(
    workflow: Workflow,
    webhook_event: WebhookEvent,
    event_payload: dict,
) -> None:
    """
    Buffer a webhook event into an aggregation window for the given workflow.

    If a closing event is detected, the corresponding opening event is removed
    from the window. Otherwise, the event is added to an existing or new window.

    Args:
        workflow: The workflow with an aggregated_webhook trigger.
        webhook_event: The stored WebhookEvent document.
        event_payload: The enriched event payload dict.
    """
    trigger_node = workflow.get_trigger_node()
    if not trigger_node:
        logger.warning("aggregation_no_trigger_node", workflow_id=str(workflow.id))
        return

    config = trigger_node.config or {}
    group_by = config.get("group_by", "site_id")
    closing_event_type = config.get("closing_event_type")
    device_key = config.get("device_key", "device_mac")
    window_seconds = int(config.get("window_seconds", 300))

    # Build group key from payload
    group_value = event_payload.get(group_by, "unknown")
    group_key = f"{group_by}:{group_value}"

    incoming_event_type = event_payload.get("type")
    device_id = event_payload.get(device_key) or event_payload.get("mac") or "unknown"

    # ── Closing event check ──────────────────────────────────────────────────
    if closing_event_type and incoming_event_type == closing_event_type:
        await _handle_closing_event(
            workflow_id=workflow.id,
            group_key=group_key,
            device_id=device_id,
            webhook_event=webhook_event,
        )
        return

    # ── Opening event — upsert into aggregation window ───────────────────────
    site_id = event_payload.get("site_id")
    site_name = event_payload.get("site_name")
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(seconds=window_seconds)

    collection = AggregationWindow.get_motor_collection()
    from pymongo import ReturnDocument

    raw = await collection.find_one_and_update(
        {
            "workflow_id": workflow.id,
            "group_key": group_key,
            "status": "collecting",
        },
        {
            "$push": {"event_ids": webhook_event.id},
            "$inc": {"event_count": 1},
            "$set": {f"device_event_map.{device_id}": str(webhook_event.id)},
            "$setOnInsert": {
                "window_start": now,
                "window_end": window_end,
                "window_seconds": window_seconds,
                "site_id": site_id,
                "site_name": site_name,
                "created_at": now,
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    if not raw:
        logger.error(
            "aggregation_upsert_failed",
            workflow_id=str(workflow.id),
            group_key=group_key,
        )
        return

    window = AggregationWindow.model_validate(raw)

    # If this is a newly created window (event_count == 1), schedule the fire job
    if window.event_count == 1:
        _schedule_fire_job(window)

    await _broadcast_window_update(window)

    logger.info(
        "aggregation_event_buffered",
        workflow_id=str(workflow.id),
        window_id=str(window.id),
        group_key=group_key,
        event_count=window.event_count,
        device_id=device_id,
    )


async def _handle_closing_event(
    workflow_id: PydanticObjectId,
    group_key: str,
    device_id: str,
    webhook_event: WebhookEvent,
) -> None:
    """Handle a closing event by removing the corresponding opening event from the window."""
    window = await AggregationWindow.find_one(
        {
            "workflow_id": workflow_id,
            "group_key": group_key,
            "status": "collecting",
        }
    )

    if not window:
        logger.debug(
            "aggregation_closing_event_no_window",
            workflow_id=str(workflow_id),
            group_key=group_key,
            device_id=device_id,
        )
        return

    opening_event_id_str = window.device_event_map.get(device_id)
    if not opening_event_id_str:
        logger.debug(
            "aggregation_closing_event_device_not_found",
            workflow_id=str(workflow_id),
            window_id=str(window.id),
            device_id=device_id,
        )
        return

    # Atomic update: remove device from map, pull event ID, decrement count
    # Note: device_id is a Mist UUID (no dots), safe for MongoDB dot-notation paths
    opening_event_id = PydanticObjectId(opening_event_id_str)
    updated = await AggregationWindow.find_one_and_update(
        {
            "_id": window.id,
            "status": "collecting",
            f"device_event_map.{device_id}": {"$exists": True},
        },
        {
            "$unset": {f"device_event_map.{device_id}": ""},
            "$pull": {"event_ids": opening_event_id},
            "$inc": {"event_count": -1},
        },
        return_document=True,
    )

    if not updated:
        logger.debug("aggregation_closing_event_already_processed", window_id=str(window.id), device_id=device_id)
        return

    if updated.event_count <= 0:
        updated.status = "cancelled"
        await updated.save()
        _cancel_fire_job(updated)
        logger.info(
            "aggregation_window_cancelled",
            workflow_id=str(workflow_id),
            window_id=str(updated.id),
            group_key=group_key,
        )
    else:
        logger.info(
            "aggregation_closing_event_processed",
            workflow_id=str(workflow_id),
            window_id=str(updated.id),
            device_id=device_id,
            remaining_events=updated.event_count,
        )

    await _broadcast_window_update(updated)


async def fire_aggregation_window(window_id: str) -> None:
    """
    Fire an aggregation window — execute the workflow with aggregated event data.

    Called by APScheduler when the window timer expires.

    Args:
        window_id: ID of the AggregationWindow to fire.
    """
    try:
        window = await AggregationWindow.get(PydanticObjectId(window_id))
        if not window:
            logger.warning("aggregation_window_not_found", window_id=window_id)
            return

        if window.status != "collecting":
            logger.info(
                "aggregation_window_not_collecting",
                window_id=window_id,
                status=window.status,
            )
            return

        # Load workflow and verify it's still enabled
        workflow = await Workflow.get(window.workflow_id)
        if not workflow:
            logger.warning("aggregation_workflow_not_found", window_id=window_id, workflow_id=str(window.workflow_id))
            window.status = "expired"
            await window.save()
            return

        if workflow.status != WorkflowStatus.ENABLED:
            logger.info(
                "aggregation_workflow_disabled",
                window_id=window_id,
                workflow_id=str(workflow.id),
            )
            window.status = "expired"
            await window.save()
            return

        # Check min_events threshold
        trigger_node = workflow.get_trigger_node()
        min_events = int((trigger_node.config or {}).get("min_events", 1)) if trigger_node else 1

        if window.event_count < min_events:
            logger.info(
                "aggregation_window_below_threshold",
                window_id=window_id,
                event_count=window.event_count,
                min_events=min_events,
            )
            window.status = "expired"
            await window.save()
            return

        # Load all buffered WebhookEvent documents
        events = await WebhookEvent.find({"_id": {"$in": window.event_ids}}).to_list()

        # Build trigger data with aggregation context — use full event payloads
        event_fields_list = [evt.payload for evt in events]

        trigger_data = {
            "aggregation": {
                "window_id": str(window.id),
                "group_key": window.group_key,
                "event_count": window.event_count,
                "window_seconds": window.window_seconds,
                "window_start": window.window_start.isoformat(),
                "window_end": window.window_end.isoformat(),
                "site_id": window.site_id,
                "site_name": window.site_name,
            },
            "events": event_fields_list,
            "first_event": event_fields_list[0] if event_fields_list else {},
            "last_event": event_fields_list[-1] if event_fields_list else {},
        }

        # Create execution record
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            trigger_type="aggregated_webhook",
            trigger_data=trigger_data,
            status=ExecutionStatus.RUNNING,
        )
        await execution.insert()
        execution.add_log(
            f"Triggered by aggregation window {window_id} "
            f"({window.event_count} events over {window.window_seconds}s)"
        )
        await execution.save()

        try:
            from app.services.mist_service_factory import create_mist_service

            mist_service = await create_mist_service()
            executor = WorkflowExecutor(mist_service=mist_service)

            result = await executor.execute_workflow(
                workflow=workflow,
                trigger_data=trigger_data,
                trigger_source="aggregated_webhook",
                execution=execution,
            )

            logger.info(
                "aggregation_workflow_executed",
                window_id=window_id,
                workflow_id=str(workflow.id),
                execution_id=str(result.id),
                status=result.status,
                event_count=window.event_count,
            )

        except Exception as e:
            # Mark execution as failed if the executor hasn't already
            if execution.status == ExecutionStatus.RUNNING:
                execution.mark_completed(ExecutionStatus.FAILED, error="Aggregated workflow execution failed")
                execution.add_log("Workflow execution error", "error")
                await execution.save()

            logger.error(
                "aggregation_workflow_execution_error",
                window_id=window_id,
                workflow_id=str(workflow.id),
                execution_id=str(execution.id),
                error=str(e),
            )

        # Update window status
        window.status = "fired"
        window.fired_at = datetime.now(timezone.utc)
        window.execution_id = execution.id
        await window.save()
        await _broadcast_window_update(window, "aggregation_fired")

    except Exception as e:
        logger.error("aggregation_fire_error", window_id=window_id, error=str(e))


async def recover_aggregation_windows() -> None:
    """
    Recover aggregation windows after application restart.

    Re-schedules APScheduler jobs for windows still collecting,
    or fires immediately for windows whose end time has already passed.
    """
    now = datetime.now(timezone.utc)

    try:
        collecting_windows = await AggregationWindow.find({"status": "collecting"}).to_list()

        if not collecting_windows:
            logger.info("aggregation_recovery_no_windows")
            return

        rescheduled = 0
        fired_immediately = 0

        for window in collecting_windows:
            window_end = window.window_end
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=timezone.utc)

            if window_end > now:
                # Window still has time — re-schedule
                _schedule_fire_job(window)
                rescheduled += 1
            else:
                # Window has expired — fire immediately
                create_background_task(
                    fire_aggregation_window(str(window.id)),
                    name=f"aggregation-recover-{window.id}",
                )
                fired_immediately += 1

        logger.info(
            "aggregation_recovery_complete",
            total=len(collecting_windows),
            rescheduled=rescheduled,
            fired_immediately=fired_immediately,
        )

    except Exception as e:
        logger.error("aggregation_recovery_error", error=str(e))


def _schedule_fire_job(window: AggregationWindow) -> None:
    """Schedule an APScheduler one-shot job to fire the aggregation window."""
    scheduler = get_scheduler()
    if not scheduler.scheduler:
        logger.warning("aggregation_scheduler_not_ready", window_id=str(window.id))
        return

    job_id = f"aggregation_{window.id}"

    # Remove existing job if present (idempotent)
    if scheduler.scheduler.get_job(job_id):
        scheduler.scheduler.remove_job(job_id)

    window_end = window.window_end
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)

    trigger = DateTrigger(run_date=window_end, timezone="UTC")

    scheduler.scheduler.add_job(
        _fire_window_async,
        trigger=trigger,
        id=job_id,
        name=f"Aggregation window {window.id}",
        kwargs={"window_id": str(window.id)},
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.debug(
        "aggregation_job_scheduled",
        window_id=str(window.id),
        fire_at=window_end.isoformat(),
    )


def _cancel_fire_job(window: AggregationWindow) -> None:
    """Cancel the APScheduler job for an aggregation window."""
    scheduler = get_scheduler()
    if not scheduler.scheduler:
        return

    job_id = f"aggregation_{window.id}"
    if scheduler.scheduler.get_job(job_id):
        scheduler.scheduler.remove_job(job_id)
        logger.debug("aggregation_job_cancelled", window_id=str(window.id))


async def _fire_window_async(window_id: str) -> None:
    """Async wrapper called by APScheduler to fire an aggregation window."""
    await fire_aggregation_window(window_id)

"""
Webhook worker - processes incoming webhooks asynchronously using Celery.
"""

from datetime import datetime, timezone
from typing import Any

import structlog
from beanie import PydanticObjectId
from celery import Celery

from app.config import settings
from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.automation.models.workflow import Workflow, WorkflowStatus
from app.modules.automation.services.executor_service import WorkflowExecutor

logger = structlog.get_logger(__name__)

# Initialize Celery
celery_app = Celery("webhook_worker", broker=settings.celery_broker_url, backend=settings.celery_result_backend)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.workflow_max_timeout,  # Hard limit
    task_soft_time_limit=settings.workflow_default_timeout,  # Soft limit
    worker_prefetch_multiplier=1,  # One task at a time per worker
    worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks
)


@celery_app.task(name="process_webhook", bind=True, max_retries=3)
def process_webhook_task(self, webhook_id: str, webhook_type: str, payload: dict, event_type: str | None = None):
    """
    Celery task to process a webhook and trigger matching workflows.

    Args:
        webhook_id: WebhookEvent ID
        webhook_type: Type of webhook
        payload: Webhook payload dict
        event_type: Specific event type within the webhook topic (e.g. "ap_offline")

    Returns:
        dict: Processing result
    """
    import asyncio

    return asyncio.run(process_webhook(webhook_id, webhook_type, payload, event_type=event_type))


async def process_webhook(
    webhook_id: str,
    webhook_type: str,
    payload: dict[str, Any],
    *,
    event_type: str | None = None,
) -> dict[str, Any]:
    """
    Process a webhook and trigger matching workflows.

    Args:
        webhook_id: WebhookEvent ID
        webhook_type: Type of webhook
        payload: Webhook payload
        event_type: Specific event type within the webhook topic (e.g. "ap_offline")

    Returns:
        dict: Processing result with matched workflows and executions
    """
    start_time = datetime.now(timezone.utc)
    webhook_event = None

    try:
        # Get webhook event record
        webhook_event = await WebhookEvent.get(PydanticObjectId(webhook_id))
        if not webhook_event:
            raise ValueError(f"Webhook event {webhook_id} not found")

        # Mark as processing (will be set to processed=True at the end)
        logger.info("webhook_processing_started", webhook_id=webhook_id, webhook_type=webhook_type)

        # Find matching workflows — filter at DB level using $elemMatch on trigger node config
        matching_workflows = await Workflow.find(
            {
                "status": WorkflowStatus.ENABLED,
                "nodes": {
                    "$elemMatch": {
                        "type": "trigger",
                        "config.trigger_type": "webhook",
                        "$or": [
                            {"config.webhook_topic": webhook_type},
                            {"config.webhook_type": webhook_type},
                        ],
                    }
                },
            }
        ).to_list()

        # Post-filter by event_type if the trigger has an event_type_filter
        if event_type:
            filtered = []
            for wf in matching_workflows:
                trigger = next((n for n in wf.nodes if n.type == "trigger"), None)
                if trigger:
                    filter_val = (trigger.config or {}).get("event_type_filter", "")
                    if filter_val and filter_val != event_type:
                        logger.debug(
                            "workflow_skipped_event_type",
                            workflow_id=str(wf.id),
                            event_type=event_type,
                            event_type_filter=filter_val,
                        )
                        continue
                filtered.append(wf)
            matching_workflows = filtered

        logger.info(
            "workflows_matched",
            webhook_id=webhook_id,
            webhook_type=webhook_type,
            event_type=event_type,
            matched_count=len(matching_workflows),
        )

        execution_results = []

        # Execute each matching workflow
        for workflow in matching_workflows:
            try:
                result = await execute_workflow_for_webhook(
                    workflow=workflow, webhook_payload=payload, webhook_id=webhook_id
                )
                execution_results.append(result)

            except Exception as e:
                logger.error(
                    "workflow_execution_failed",
                    workflow_id=str(workflow.id),
                    workflow_name=workflow.name,
                    webhook_id=webhook_id,
                    error=str(e),
                )
                execution_results.append(
                    {
                        "workflow_id": str(workflow.id),
                        "workflow_name": workflow.name,
                        "status": "failed",
                        "error": "Workflow execution failed",
                    }
                )

        # Update webhook event with results
        webhook_event.processed = True
        webhook_event.processed_at = datetime.now(timezone.utc)
        webhook_event.matched_workflows = [workflow.id for workflow in matching_workflows]
        webhook_event.executions_triggered = [
            PydanticObjectId(r["execution_id"]) for r in execution_results if r.get("execution_id")
        ]
        await webhook_event.save()

        processing_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        logger.info(
            "webhook_processing_completed",
            webhook_id=webhook_id,
            matched_workflows=len(matching_workflows),
            executions=len(execution_results),
            processing_time_ms=processing_time_ms,
        )

        # Broadcast processing update to WebSocket monitor
        from app.core.websocket import ws_manager

        try:
            await ws_manager.broadcast(
                "webhook:monitor",
                {
                    "type": "webhook_processed",
                    "data": {
                        "id": webhook_id,
                        "processed": True,
                        "matched_workflows": [str(wid) for wid in webhook_event.matched_workflows],
                        "executions_triggered": [str(eid) for eid in webhook_event.executions_triggered],
                        "processed_at": webhook_event.processed_at.isoformat() if webhook_event.processed_at else None,
                    },
                },
            )
        except Exception as e:
            logger.debug("ws_broadcast_failed", error=str(e))

        return {
            "webhook_id": webhook_id,
            "webhook_type": webhook_type,
            "matched_workflows": len(matching_workflows),
            "executions": execution_results,
            "processing_time_ms": processing_time_ms,
        }

    except Exception as e:
        logger.error("webhook_processing_error", webhook_id=webhook_id, error=str(e))

        # Mark webhook as failed
        if webhook_event:
            webhook_event.processed = True
            webhook_event.processed_at = datetime.now(timezone.utc)
            await webhook_event.save()

        raise


async def execute_workflow_for_webhook(
    workflow: Workflow, webhook_payload: dict[str, Any], webhook_id: str
) -> dict[str, Any]:
    """
    Execute a single workflow triggered by a webhook.

    Args:
        workflow: Workflow to execute
        webhook_payload: Webhook payload data
        webhook_id: ID of triggering webhook

    Returns:
        dict: Execution result
    """
    logger.info(
        "executing_workflow_for_webhook",
        workflow_id=str(workflow.id),
        workflow_name=workflow.name,
        webhook_id=webhook_id,
    )

    # Create execution record
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        trigger_type="webhook",
        trigger_data=webhook_payload,
        status=ExecutionStatus.RUNNING,
    )
    await execution.insert()
    execution.add_log(f"Triggered by webhook {webhook_id}")
    await execution.save()

    try:
        from app.services.mist_service_factory import create_mist_service

        mist_service = await create_mist_service()
        executor = WorkflowExecutor(mist_service=mist_service)

        # Execute workflow — pass the pre-created execution to avoid duplicates
        result = await executor.execute_workflow(
            workflow=workflow,
            trigger_data=webhook_payload,
            trigger_source="webhook",
            execution=execution,
        )

        logger.info(
            "workflow_execution_completed",
            workflow_id=str(workflow.id),
            execution_id=str(result.id),
            status=result.status,
            duration_ms=result.duration_ms,
            trigger_condition_passed=result.trigger_condition_passed,
            nodes_executed=result.nodes_executed,
        )

        return {
            "workflow_id": str(workflow.id),
            "workflow_name": workflow.name,
            "execution_id": str(result.id),
            "status": result.status,
            "trigger_condition_passed": result.trigger_condition_passed,
            "nodes_executed": result.nodes_executed,
            "nodes_succeeded": result.nodes_succeeded,
            "nodes_failed": result.nodes_failed,
            "duration_ms": result.duration_ms,
        }

    except Exception as e:
        # Mark execution as failed if the executor hasn't already done so
        # (e.g. MistService init failure happens before the executor runs)
        if execution.status == ExecutionStatus.RUNNING:
            execution.mark_completed(ExecutionStatus.FAILED, error="Workflow execution failed")
            execution.add_log("Workflow execution error", "error")
            await execution.save()

        logger.error(
            "workflow_execution_error", workflow_id=str(workflow.id), execution_id=str(execution.id), error=str(e)
        )

        return {
            "workflow_id": str(workflow.id),
            "workflow_name": workflow.name,
            "execution_id": str(execution.id),
            "status": "failed",
            "error": "Workflow execution failed",
        }

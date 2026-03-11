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
def process_webhook_task(self, webhook_id: str, webhook_type: str, payload: dict):
    """
    Celery task to process a webhook and trigger matching workflows.

    Args:
        webhook_id: WebhookEvent ID
        webhook_type: Type of webhook
        payload: Webhook payload dict

    Returns:
        dict: Processing result
    """
    import asyncio

    return asyncio.run(process_webhook(webhook_id, webhook_type, payload))


async def process_webhook(webhook_id: str, webhook_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Process a webhook and trigger matching workflows.

    Args:
        webhook_id: WebhookEvent ID
        webhook_type: Type of webhook
        payload: Webhook payload

    Returns:
        dict: Processing result with matched workflows and executions
    """
    start_time = datetime.now(timezone.utc)

    try:
        # Get webhook event record
        webhook_event = await WebhookEvent.get(PydanticObjectId(webhook_id))
        if not webhook_event:
            raise ValueError(f"Webhook event {webhook_id} not found")

        # Mark as processing (will be set to processed=True at the end)
        logger.info("webhook_processing_started", webhook_id=webhook_id, webhook_type=webhook_type)

        # Find matching workflows — graph model stores trigger config in nodes
        all_enabled = await Workflow.find(Workflow.status == WorkflowStatus.ENABLED).to_list()
        matching_workflows = []
        for wf in all_enabled:
            trigger_node = wf.get_trigger_node()
            if not trigger_node:
                continue
            cfg = trigger_node.config
            if cfg.get("trigger_type") == "webhook" and (cfg.get("webhook_topic") or cfg.get("webhook_type")) == webhook_type:
                matching_workflows.append(wf)

        logger.info(
            "workflows_matched", webhook_id=webhook_id, webhook_type=webhook_type, matched_count=len(matching_workflows)
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
                        "error": str(e),
                    }
                )

        # Update webhook event with results
        webhook_event.processed = True
        webhook_event.processed_at = datetime.now(timezone.utc)
        webhook_event.matched_workflows = [workflow.id for workflow in matching_workflows]
        await webhook_event.save()

        processing_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        logger.info(
            "webhook_processing_completed",
            webhook_id=webhook_id,
            matched_workflows=len(matching_workflows),
            executions=len(execution_results),
            processing_time_ms=processing_time_ms,
        )

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
            actions_executed=result.actions_executed,
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
            execution.mark_completed(ExecutionStatus.FAILED, error=str(e))
            execution.add_log(f"Workflow execution error: {e}", "error")
            await execution.save()

        logger.error(
            "workflow_execution_error", workflow_id=str(workflow.id), execution_id=str(execution.id), error=str(e)
        )

        return {
            "workflow_id": str(workflow.id),
            "workflow_name": workflow.name,
            "execution_id": str(execution.id),
            "status": "failed",
            "error": str(e),
        }


def queue_webhook_processing(webhook_id: str, webhook_type: str, payload: dict) -> str:
    """
    Queue a webhook for asynchronous processing.

    Args:
        webhook_id: WebhookEvent ID
        webhook_type: Type of webhook
        payload: Webhook payload

    Returns:
        str: Celery task ID
    """
    task = process_webhook_task.delay(webhook_id, webhook_type, payload)

    logger.info("webhook_queued", webhook_id=webhook_id, webhook_type=webhook_type, task_id=task.id)

    return task.id

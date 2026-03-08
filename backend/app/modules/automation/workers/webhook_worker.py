"""
Webhook worker - processes incoming webhooks asynchronously using Celery.
"""

from datetime import datetime, timezone
from typing import Any
import structlog
from celery import Celery
from beanie import PydanticObjectId

from app.modules.automation.models.workflow import Workflow, TriggerType
from app.modules.automation.models.webhook import WebhookEvent
from app.modules.automation.models.execution import WorkflowExecution, ExecutionStatus
from app.modules.automation.services.executor_service import WorkflowExecutor
from app.services.mist_service import MistService
from app.config import settings

logger = structlog.get_logger(__name__)

# Initialize Celery
celery_app = Celery(
    'webhook_worker',
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend
)

# Configure Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.workflow_max_timeout,  # Hard limit
    task_soft_time_limit=settings.workflow_default_timeout,  # Soft limit
    worker_prefetch_multiplier=1,  # One task at a time per worker
    worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks
)


@celery_app.task(name='process_webhook', bind=True, max_retries=3)
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
    
    # Run async function in sync context
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        process_webhook(webhook_id, webhook_type, payload)
    )


async def process_webhook(
    webhook_id: str,
    webhook_type: str,
    payload: dict[str, Any]
) -> dict[str, Any]:
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
        logger.info(
            "webhook_processing_started",
            webhook_id=webhook_id,
            webhook_type=webhook_type
        )

        # Find matching workflows
        matching_workflows = await Workflow.find(
            Workflow.enabled == True,
            Workflow.trigger.type == TriggerType.WEBHOOK,
            Workflow.trigger.webhook_topic == webhook_type
        ).to_list()

        logger.info(
            "workflows_matched",
            webhook_id=webhook_id,
            webhook_type=webhook_type,
            matched_count=len(matching_workflows)
        )

        execution_results = []

        # Execute each matching workflow
        for workflow in matching_workflows:
            try:
                result = await execute_workflow_for_webhook(
                    workflow=workflow,
                    webhook_payload=payload,
                    webhook_id=webhook_id
                )
                execution_results.append(result)

            except Exception as e:
                logger.error(
                    "workflow_execution_failed",
                    workflow_id=str(workflow.id),
                    workflow_name=workflow.name,
                    webhook_id=webhook_id,
                    error=str(e)
                )
                execution_results.append({
                    "workflow_id": str(workflow.id),
                    "workflow_name": workflow.name,
                    "status": "failed",
                    "error": str(e)
                })

        # Update webhook event with results
        webhook_event.processed = True
        webhook_event.processed_at = datetime.now(timezone.utc)
        webhook_event.matched_workflows = [
            workflow.id for workflow in matching_workflows
        ]
        await webhook_event.save()

        processing_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        logger.info(
            "webhook_processing_completed",
            webhook_id=webhook_id,
            matched_workflows=len(matching_workflows),
            executions=len(execution_results),
            processing_time_ms=processing_time_ms
        )

        return {
            "webhook_id": webhook_id,
            "webhook_type": webhook_type,
            "matched_workflows": len(matching_workflows),
            "executions": execution_results,
            "processing_time_ms": processing_time_ms,
        }

    except Exception as e:
        logger.error(
            "webhook_processing_error",
            webhook_id=webhook_id,
            error=str(e)
        )

        # Mark webhook as failed
        if webhook_event:
            webhook_event.processed = True
            webhook_event.processed_at = datetime.now(timezone.utc)
            await webhook_event.save()

        raise


async def execute_workflow_for_webhook(
    workflow: Workflow,
    webhook_payload: dict[str, Any],
    webhook_id: str
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
        webhook_id=webhook_id
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

    try:
        # Initialize executor
        mist_service = MistService(
            api_token=settings.mist_api_token,
            org_id=settings.mist_org_id
        )
        executor = WorkflowExecutor(mist_service=mist_service)

        # Execute workflow
        result = await executor.execute_workflow(
            workflow=workflow,
            trigger_data=webhook_payload,
            trigger_source="webhook"
        )

        # Determine final status
        if result.get("filters_passed", False):
            if result.get("all_actions_succeeded", False):
                final_status = ExecutionStatus.SUCCESS
                final_error = None
            else:
                final_status = ExecutionStatus.FAILED
                final_error = "Some actions failed"
        else:
            # Filters didn't pass - this is not an error
            final_status = ExecutionStatus.FILTERED
            final_error = "Filters did not match"

        execution.mark_completed(final_status, error=final_error)
        await execution.save()

        logger.info(
            "workflow_execution_completed",
            workflow_id=str(workflow.id),
            execution_id=str(execution.id),
            status=execution.status,
            duration_ms=execution.duration_ms,
            filters_passed=result.get("filters_passed", False),
            actions_executed=execution.actions_executed
        )

        return {
            "workflow_id": str(workflow.id),
            "workflow_name": workflow.name,
            "execution_id": str(execution.id),
            "status": execution.status,
            "filters_passed": result.get("filters_passed", False),
            "actions_executed": execution.actions_executed,
            "actions_succeeded": execution.actions_succeeded,
            "actions_failed": execution.actions_failed,
            "duration_ms": execution.duration_ms,
        }

    except Exception as e:
        # Mark execution as failed
        execution.mark_completed(ExecutionStatus.FAILED, error=str(e))
        await execution.save()

        logger.error(
            "workflow_execution_error",
            workflow_id=str(workflow.id),
            execution_id=str(execution.id),
            error=str(e)
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
    
    logger.info(
        "webhook_queued",
        webhook_id=webhook_id,
        webhook_type=webhook_type,
        task_id=task.id
    )
    
    return task.id

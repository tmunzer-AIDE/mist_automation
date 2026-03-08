"""
Cron workflow executor - handles scheduled workflow execution.
"""

from datetime import datetime, timezone
from typing import Any, Optional
import structlog
from beanie import PydanticObjectId

from app.modules.automation.models.workflow import Workflow, WorkflowStatus
from app.modules.automation.models.execution import WorkflowExecution, ExecutionStatus
from app.modules.automation.services.executor_service import WorkflowExecutor
from app.services.mist_service import MistService
from app.config import settings

logger = structlog.get_logger(__name__)


async def execute_cron_workflow(workflow_id: str) -> dict[str, Any]:
    """
    Execute a cron-triggered workflow.

    Args:
        workflow_id: Workflow ID to execute

    Returns:
        dict: Execution result

    Raises:
        ValueError: If workflow not found or not enabled
    """
    try:
        # Get workflow
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        if workflow.status != WorkflowStatus.ENABLED:
            raise ValueError(f"Workflow {workflow_id} is disabled")

        logger.info(
            "cron_workflow_execution_started",
            workflow_id=workflow_id,
            workflow_name=workflow.name
        )

        # Create execution record
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            trigger_type="cron",
            status=ExecutionStatus.RUNNING,
        )
        await execution.insert()

        # Initialize executor
        mist_service = MistService(
            api_token=settings.mist_api_token,
            org_id=settings.mist_org_id
        )
        executor = WorkflowExecutor(mist_service=mist_service)

        try:
            # Execute workflow with empty trigger data (no webhook payload)
            result = await executor.execute_workflow(
                workflow=workflow,
                trigger_data={
                    "trigger_type": "cron",
                    "scheduled_time": datetime.now(timezone.utc).isoformat(),
                },
                trigger_source="cron"
            )

            # Mark as completed
            if result.get("filters_passed", False) and result.get("all_actions_succeeded", False):
                execution.mark_completed(ExecutionStatus.SUCCESS)
            elif not result.get("filters_passed", False):
                execution.mark_completed(ExecutionStatus.SUCCESS, error="Filters did not pass")
            else:
                execution.mark_completed(ExecutionStatus.FAILED, error="Some actions failed")

            await execution.save()

            logger.info(
                "cron_workflow_execution_completed",
                workflow_id=workflow_id,
                execution_id=str(execution.id),
                status=execution.status,
                duration_ms=execution.duration_ms
            )

            return {
                "workflow_id": workflow_id,
                "execution_id": str(execution.id),
                "status": execution.status,
                "duration_ms": execution.duration_ms,
                "filters_passed": result.get("filters_passed", False),
                "actions_executed": result.get("actions_executed", 0),
            }

        except Exception as e:
            # Mark execution as failed
            execution.mark_completed(ExecutionStatus.FAILED, error=str(e))
            await execution.save()

            logger.error(
                "cron_workflow_execution_error",
                workflow_id=workflow_id,
                execution_id=str(execution.id),
                error=str(e)
            )
            raise

    except Exception as e:
        logger.error(
            "cron_workflow_execution_failed",
            workflow_id=workflow_id,
            error=str(e)
        )
        raise


async def get_cron_workflow_status(workflow_id: str) -> dict[str, Any]:
    """
    Get status and recent executions of a cron workflow.

    Args:
        workflow_id: Workflow ID

    Returns:
        dict: Workflow status information
    """
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Get recent executions
        recent_executions = await WorkflowExecution.find(
            WorkflowExecution.workflow_id == workflow.id,
            WorkflowExecution.trigger_type == "cron"
        ).sort("-started_at").limit(10).to_list()

        # Calculate success rate
        total_executions = len(recent_executions)
        successful_executions = sum(
            1 for e in recent_executions 
            if e.status == ExecutionStatus.SUCCESS
        )
        success_rate = (successful_executions / total_executions * 100) if total_executions > 0 else 0

        # Get last execution info
        last_execution = recent_executions[0] if recent_executions else None

        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "enabled": workflow.status == WorkflowStatus.ENABLED,
            "cron_expression": workflow.trigger.cron_expression if workflow.trigger else None,
            "total_executions": total_executions,
            "success_rate": round(success_rate, 2),
            "last_execution": {
                "execution_id": str(last_execution.id),
                "status": last_execution.status,
                "started_at": last_execution.started_at.isoformat(),
                "duration_ms": last_execution.duration_ms,
            } if last_execution else None,
            "recent_executions": [
                {
                    "execution_id": str(e.id),
                    "status": e.status,
                    "started_at": e.started_at.isoformat(),
                    "duration_ms": e.duration_ms,
                }
                for e in recent_executions
            ]
        }

    except Exception as e:
        logger.error(
            "failed_to_get_cron_workflow_status",
            workflow_id=workflow_id,
            error=str(e)
        )
        raise

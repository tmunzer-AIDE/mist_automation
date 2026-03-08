"""
Workflow executor service for running workflows and executing actions.
"""

from datetime import datetime, timezone
from typing import Any, Optional
import asyncio
import structlog
import httpx

from app.modules.automation.models.workflow import (
    Workflow,
    WorkflowAction,
    ActionType,
)
from app.utils.filters import evaluate_filters
from app.utils.variables import substitute_variables, substitute_in_dict
from app.modules.automation.models.execution import WorkflowExecution, ExecutionStatus, ActionExecutionResult
from app.services.mist_service import MistService
from app.core.exceptions import WorkflowExecutionError, WorkflowTimeoutError
from app.config import settings

logger = structlog.get_logger(__name__)


class WorkflowExecutor:
    """Service for executing workflows and actions."""

    def __init__(self, mist_service: Optional[MistService] = None):
        """
        Initialize executor.

        Args:
            mist_service: Optional MistService instance
        """
        self.mist_service = mist_service or MistService()
        self.variable_context: dict[str, Any] = {}

    async def execute_workflow(
        self,
        workflow: Workflow,
        trigger_data: dict[str, Any],
        trigger_source: str = "webhook",
    ) -> WorkflowExecution:
        """
        Execute a workflow with given trigger data.

        Args:
            workflow: Workflow to execute
            trigger_data: Trigger payload (webhook data or cron context)
            trigger_source: Source of trigger (webhook, cron, manual)

        Returns:
            WorkflowExecution record

        Raises:
            WorkflowExecutionError: If execution fails
            WorkflowTimeoutError: If execution exceeds timeout
        """
        start_time = datetime.now(timezone.utc)
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            trigger_type=trigger_source or "manual",
            trigger_data=trigger_data,
            status=ExecutionStatus.RUNNING,
        )
        await execution.insert()

        logger.info(
            "workflow_execution_started",
            workflow_id=str(workflow.id),
            execution_id=str(execution.id),
            trigger_source=trigger_source,
        )

        # Initialize variable context with trigger data
        self.variable_context = {"trigger": trigger_data, "results": {}}

        try:
            # Execute with timeout
            execution = await asyncio.wait_for(
                self._execute_workflow_internal(workflow, execution),
                timeout=workflow.timeout_seconds,
            )

        except asyncio.TimeoutError:
            execution.status = ExecutionStatus.TIMEOUT
            execution.error_message = f"Workflow exceeded timeout of {workflow.timeout_seconds} seconds"
            execution.timed_out = True
            await execution.save()

            logger.warning(
                "workflow_execution_timeout",
                workflow_id=str(workflow.id),
                execution_id=str(execution.id),
                timeout=workflow.timeout_seconds,
            )

            # Update workflow stats
            workflow.failure_count += 1
            workflow.last_execution = start_time
            workflow.last_failure = start_time
            await workflow.save()

            raise WorkflowTimeoutError(f"Workflow execution timed out after {workflow.timeout_seconds} seconds")

        except Exception as e:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = str(e)
            await execution.save()

            logger.error(
                "workflow_execution_failed",
                workflow_id=str(workflow.id),
                execution_id=str(execution.id),
                error=str(e),
            )

            # Update workflow stats
            workflow.failure_count += 1
            workflow.last_execution = start_time
            workflow.last_failure = start_time
            await workflow.save()

            raise WorkflowExecutionError(f"Workflow execution failed: {str(e)}")

        # Calculate duration
        end_time = datetime.now(timezone.utc)
        execution.duration_ms = int((end_time - start_time).total_seconds() * 1000)
        await execution.save()

        # Update workflow stats
        workflow.execution_count += 1
        workflow.last_execution = start_time
        if execution.status == ExecutionStatus.SUCCESS:
            workflow.success_count += 1
            workflow.last_success = start_time
        else:
            workflow.failure_count += 1
            workflow.last_failure = start_time
        await workflow.save()

        logger.info(
            "workflow_execution_completed",
            workflow_id=str(workflow.id),
            execution_id=str(execution.id),
            status=execution.status,
            duration_ms=execution.duration_ms,
        )

        return execution

    async def _execute_workflow_internal(
        self,
        workflow: Workflow,
        execution: WorkflowExecution,
    ) -> WorkflowExecution:
        """Internal workflow execution logic."""

        # Step 1: Evaluate filters
        filter_result = evaluate_filters(
            [f.model_dump(mode="json") for f in workflow.filters],
            self.variable_context.get("trigger", {}),
        )
        filters_passed = filter_result["passed"]
        execution.filter_results = filter_result["filter_results"]
        await execution.save()

        if not filters_passed:
            execution.status = ExecutionStatus.FILTERED
            execution.error_message = "Workflow filters did not match"
            await execution.save()
            logger.info(
                "workflow_filtered_out",
                workflow_id=str(workflow.id),
                execution_id=str(execution.id),
            )
            return execution

        # Step 2: Execute actions
        all_success = await self._execute_actions(workflow.actions, execution)

        # Set final status
        if all_success:
            execution.status = ExecutionStatus.SUCCESS
        else:
            # Check if any actions succeeded
            has_success = any(ar.status == "success" for ar in execution.action_results)
            execution.status = ExecutionStatus.PARTIAL if has_success else ExecutionStatus.FAILED

        await execution.save()
        return execution

    async def _execute_actions(
        self,
        actions: list[WorkflowAction],
        execution: WorkflowExecution,
    ) -> bool:
        """
        Execute all workflow actions.

        Args:
            actions: List of actions to execute
            execution: Execution record

        Returns:
            True if all actions succeeded
        """
        all_success = True

        for i, action in enumerate(actions):
            if not action.enabled:
                logger.debug("action_skipped_disabled", action_index=i, action_name=action.name)
                continue

            try:
                result = await self._execute_action(action, i)
                execution.add_action_result(result)
                await execution.save()

                if result.status != "success":
                    all_success = False
                    if not action.continue_on_error:
                        logger.warning(
                            "action_failed_stopping_workflow",
                            action_index=i,
                            action_name=action.name,
                        )
                        break

            except Exception as e:
                logger.error(
                    "action_execution_error",
                    action_index=i,
                    action_name=action.name,
                    error=str(e),
                )
                # Create ActionExecutionResult for error case
                result = ActionExecutionResult(
                    action_name=action.name,
                    status="failed",
                    started_at=datetime.now(timezone.utc),
                    error=str(e),
                )
                execution.add_action_result(result)
                await execution.save()

                all_success = False
                if not action.continue_on_error:
                    break

        return all_success

    async def _execute_action(self, action: WorkflowAction, index: int) -> ActionExecutionResult:
        """Execute a single action with retries."""
        
        started_at = datetime.now(timezone.utc)
        last_error = None
        retry_count = 0
        
        for attempt in range(action.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(
                        "action_retry",
                        action_name=action.name,
                        attempt=attempt,
                        max_retries=action.max_retries,
                    )
                    await asyncio.sleep(action.retry_delay)
                    retry_count = attempt

                # Execute based on action type
                if action.type == ActionType.MIST_API_GET:
                    result = await self._execute_mist_api("GET", action)
                elif action.type == ActionType.MIST_API_POST:
                    result = await self._execute_mist_api("POST", action)
                elif action.type == ActionType.MIST_API_PUT:
                    result = await self._execute_mist_api("PUT", action)
                elif action.type == ActionType.MIST_API_DELETE:
                    result = await self._execute_mist_api("DELETE", action)
                elif action.type == ActionType.WEBHOOK:
                    result = await self._execute_webhook(action)
                elif action.type == ActionType.DELAY:
                    result = await self._execute_delay(action)
                else:
                    raise NotImplementedError(f"Action type {action.type} not implemented")

                completed_at = datetime.now(timezone.utc)
                duration_ms = int((completed_at - started_at).total_seconds() * 1000)
                
                return ActionExecutionResult(
                    action_name=action.name,
                    status="success",
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    output=result,
                    retry_count=retry_count,
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "action_attempt_failed",
                    action_name=action.name,
                    attempt=attempt,
                    error=str(e),
                )

        # All retries failed
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        
        return ActionExecutionResult(
            action_name=action.name,
            status="failed",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            error=last_error,
            retry_count=retry_count,
        )

    async def _execute_mist_api(self, method: str, action: WorkflowAction) -> dict[str, Any]:
        """Execute a Mist API action (GET, POST, PUT, or DELETE)."""
        trigger_data = self.variable_context.get("trigger")
        api_results = self.variable_context.get("results")

        endpoint = substitute_variables(action.api_endpoint, webhook_data=trigger_data, api_results=api_results)
        params = substitute_in_dict(action.api_params or {}, webhook_data=trigger_data, api_results=api_results)

        if method in ("POST", "PUT"):
            body = substitute_in_dict(action.api_body or {}, webhook_data=trigger_data, api_results=api_results)
            result = await getattr(self.mist_service, f"api_{method.lower()}")(endpoint, body, params)
        elif method == "DELETE":
            await self.mist_service.api_delete(endpoint, params)
            result = {"status": "deleted"}
        else:  # GET
            result = await self.mist_service.api_get(endpoint, params)

        logger.info(f"mist_api_{method.lower()}_executed", endpoint=endpoint)
        return result

    async def _execute_webhook(self, action: WorkflowAction) -> dict[str, Any]:
        """Execute webhook action."""
        trigger_data = self.variable_context.get("trigger")
        api_results = self.variable_context.get("results")
        url = substitute_variables(action.webhook_url, webhook_data=trigger_data, api_results=api_results)
        headers = substitute_in_dict(action.webhook_headers or {}, webhook_data=trigger_data, api_results=api_results)
        body = substitute_in_dict(action.webhook_body or {}, webhook_data=trigger_data, api_results=api_results)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()

        logger.info("webhook_executed", url=url, status_code=response.status_code)

        return {"status_code": response.status_code, "response": response.text[:1000]}

    async def _execute_delay(self, action: WorkflowAction) -> dict[str, Any]:
        """Execute delay action."""
        await asyncio.sleep(action.delay_seconds)
        logger.info("delay_executed", seconds=action.delay_seconds)

        return {"delayed_seconds": action.delay_seconds}


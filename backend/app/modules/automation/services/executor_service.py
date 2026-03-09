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
from app.utils.variables import substitute_variables, substitute_in_dict, build_context, get_nested_value
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
        execution: WorkflowExecution | None = None,
    ) -> WorkflowExecution:
        """
        Execute a workflow with given trigger data.

        Args:
            workflow: Workflow to execute
            trigger_data: Trigger payload (webhook data or cron context)
            trigger_source: Source of trigger (webhook, cron, manual)
            execution: Optional pre-created execution record (e.g. from webhook/cron worker)

        Returns:
            WorkflowExecution record

        Raises:
            WorkflowExecutionError: If execution fails
            WorkflowTimeoutError: If execution exceeds timeout
        """
        start_time = datetime.now(timezone.utc)
        if execution is None:
            execution = WorkflowExecution(
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                trigger_type=trigger_source or "manual",
                trigger_data=trigger_data,
                status=ExecutionStatus.RUNNING,
            )
            await execution.insert()
        else:
            execution.status = ExecutionStatus.RUNNING
            await execution.save()

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
            execution.error = f"Workflow exceeded timeout of {workflow.timeout_seconds} seconds"
            execution.add_log(f"Workflow timed out after {workflow.timeout_seconds} seconds", "error")
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
            execution.error = str(e)
            execution.add_log(f"Workflow execution failed: {e}", "error")
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

        # Step 1: Evaluate trigger condition
        if workflow.trigger.condition:
            execution.trigger_condition = workflow.trigger.condition
            execution.add_log(f"Evaluating trigger condition: {workflow.trigger.condition}")
            condition_passed = self._evaluate_condition_expression(workflow.trigger.condition)
            execution.trigger_condition_passed = condition_passed
            execution.add_log(f"Trigger condition result: {'passed' if condition_passed else 'not met'}")
            await execution.save()

            if not condition_passed:
                execution.status = ExecutionStatus.FILTERED
                execution.add_log("Workflow filtered out — trigger condition not met", "info")
                await execution.save()
                logger.info(
                    "workflow_filtered_out",
                    workflow_id=str(workflow.id),
                    execution_id=str(execution.id),
                    condition=workflow.trigger.condition,
                )
                return execution
        else:
            execution.trigger_condition_passed = True
            await execution.save()

        # Step 2: Extract trigger variables via save_as bindings
        if workflow.trigger.save_as:
            trigger_data = self.variable_context.get("trigger", {})
            self._store_save_as_variables(workflow.trigger.save_as, trigger_data)

        # Step 3: Execute actions
        execution.add_log(f"Starting execution of {len(workflow.actions)} action(s)")
        await execution.save()
        all_success = await self._execute_actions(workflow.actions, execution)

        # Set final status
        if all_success:
            execution.status = ExecutionStatus.SUCCESS
        else:
            # Check if any actions succeeded
            has_success = any(ar.status == "success" for ar in execution.action_results)
            execution.status = ExecutionStatus.PARTIAL if has_success else ExecutionStatus.FAILED

        # Store variable context for audit
        execution.variables = self.variable_context.get("results", {})
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
                execution.add_log(f"Action [{i}] '{action.name}' skipped (disabled)")
                logger.debug("action_skipped_disabled", action_index=i, action_name=action.name)
                continue

            execution.add_log(f"Action [{i}] '{action.name}' started ({action.type})")

            try:
                result = await self._execute_action(action, i, execution)
                execution.add_action_result(result)

                if result.status == "success":
                    execution.add_log(f"Action [{i}] '{action.name}' succeeded ({result.duration_ms}ms)")
                else:
                    execution.add_log(
                        f"Action [{i}] '{action.name}' failed: {result.error}",
                        "error",
                    )

                # Store output as named variables if save_as is set
                if action.save_as and result.status == "success" and result.output:
                    self._store_save_as_variables(action.save_as, result.output)

                await execution.save()

                if result.status != "success":
                    all_success = False
                    if not action.continue_on_error:
                        execution.add_log(f"Stopping workflow — action '{action.name}' failed and continue_on_error is off", "warning")
                        logger.warning(
                            "action_failed_stopping_workflow",
                            action_index=i,
                            action_name=action.name,
                        )
                        await execution.save()
                        break

            except Exception as e:
                logger.error(
                    "action_execution_error",
                    action_index=i,
                    action_name=action.name,
                    error=str(e),
                )
                execution.add_log(f"Action [{i}] '{action.name}' exception: {e}", "error")
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

    async def _execute_action(
        self, action: WorkflowAction, index: int, execution: WorkflowExecution | None = None
    ) -> ActionExecutionResult:
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
                elif action.type == ActionType.CONDITION:
                    result = await self._execute_condition(action, execution)
                elif action.type == ActionType.SET_VARIABLE:
                    result = await self._execute_set_variable(action)
                elif action.type == ActionType.FOR_EACH:
                    result = await self._execute_for_each(action, execution)
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
            result = await getattr(self.mist_service, f"api_{method.lower()}")(endpoint, body)
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

    def _evaluate_condition_expression(self, expression: str) -> bool:
        """
        Evaluate a condition expression using Jinja2.

        The expression is rendered as a Jinja2 template with the current
        variable context. The result is interpreted as truthy/falsy.

        Args:
            expression: Condition expression (e.g. "{{ event.severity == 'critical' }}")

        Returns:
            True if condition is truthy, False otherwise
        """
        from jinja2 import Environment, ChainableUndefined

        trigger_data = self.variable_context.get("trigger")
        api_results = self.variable_context.get("results")
        context = build_context(webhook_data=trigger_data, api_results=api_results)

        env = Environment(undefined=ChainableUndefined)
        rendered = env.from_string(expression).render(context).strip()

        # Interpret rendered result as boolean
        return rendered.lower() not in ("", "false", "0", "none", "null", "undefined")

    def _store_save_as_variables(self, bindings: list, output: dict[str, Any]) -> None:
        """Store variables extracted from action output via save_as bindings."""
        from jinja2 import Environment, ChainableUndefined
        import json

        for binding in bindings:
            if not binding.expression:
                # No expression — store full output
                self.variable_context["results"][binding.name] = output
            else:
                # Evaluate Jinja2 expression with output available
                trigger_data = self.variable_context.get("trigger")
                api_results = self.variable_context.get("results")
                context = build_context(webhook_data=trigger_data, api_results=api_results)
                context["output"] = output
                if "loop" in self.variable_context:
                    context["loop"] = self.variable_context["loop"]
                if "item" in self.variable_context:
                    context["item"] = self.variable_context["item"]

                env = Environment(undefined=ChainableUndefined)
                rendered = env.from_string(binding.expression).render(context).strip()

                # Try to parse as JSON for structured data
                try:
                    value = json.loads(rendered)
                except (json.JSONDecodeError, ValueError):
                    value = rendered

                self.variable_context["results"][binding.name] = value
                logger.debug("save_as_variable_stored", name=binding.name, value=str(value)[:200])

    async def _execute_condition(
        self, action: WorkflowAction, execution: WorkflowExecution
    ) -> dict[str, Any]:
        """
        Execute a condition action with multiple branches.

        Evaluates branches in order; the first matching branch's actions are
        executed. If no branch matches, else_actions are executed (if defined).
        """
        matched_branch = None
        matched_index = None

        for i, branch in enumerate(action.branches or []):
            if self._evaluate_condition_expression(branch.condition):
                matched_branch = branch
                matched_index = i
                break

        if matched_branch is not None:
            logger.info(
                "condition_branch_matched",
                action_name=action.name,
                branch_index=matched_index,
                condition=matched_branch.condition,
            )
            await self._execute_actions(matched_branch.actions, execution)
            return {
                "matched_branch": matched_index,
                "condition": matched_branch.condition,
            }

        if action.else_actions:
            logger.info(
                "condition_else_branch",
                action_name=action.name,
            )
            await self._execute_actions(action.else_actions, execution)
            return {"matched_branch": "else"}

        logger.info(
            "condition_no_match",
            action_name=action.name,
        )
        return {"matched_branch": None}

    async def _execute_set_variable(self, action: WorkflowAction) -> dict[str, Any]:
        """Execute a set_variable action: evaluate a Jinja2 expression and store the result."""
        trigger_data = self.variable_context.get("trigger")
        api_results = self.variable_context.get("results")
        context = build_context(webhook_data=trigger_data, api_results=api_results)

        # Also inject loop context if present
        if "loop" in self.variable_context:
            context["loop"] = self.variable_context["loop"]
        if "item" in self.variable_context:
            context["item"] = self.variable_context["item"]

        from jinja2 import Environment, ChainableUndefined
        env = Environment(undefined=ChainableUndefined)
        rendered = env.from_string(action.variable_expression).render(context).strip()

        # Try to parse as JSON for structured data
        import json
        try:
            value = json.loads(rendered)
        except (json.JSONDecodeError, ValueError):
            value = rendered

        self.variable_context["results"][action.variable_name] = value
        logger.info("set_variable_executed", variable_name=action.variable_name, value=str(value)[:200])
        return {"variable_name": action.variable_name, "value": value}

    async def _execute_for_each(
        self, action: WorkflowAction, execution: WorkflowExecution
    ) -> dict[str, Any]:
        """
        Execute a for_each loop action.

        Resolves the loop_over dot-path, iterates over the resulting list,
        and executes loop_actions for each item.
        """
        # Resolve the collection to iterate over
        collection = get_nested_value(self.variable_context, action.loop_over)
        if collection is None:
            raise ValueError(f"for_each: '{action.loop_over}' resolved to None")
        if not isinstance(collection, list):
            raise ValueError(f"for_each: '{action.loop_over}' is not a list (got {type(collection).__name__})")

        # Cap at max_iterations
        items = collection[:action.max_iterations]
        loop_variable = action.loop_variable or "item"
        iteration_count = 0

        for i, item in enumerate(items):
            # Set loop context
            self.variable_context["loop"] = {loop_variable: item, "index": i}
            self.variable_context["item"] = item

            await self._execute_actions(action.loop_actions or [], execution)
            iteration_count += 1

        # Clean up loop context
        self.variable_context.pop("loop", None)
        self.variable_context.pop("item", None)

        logger.info(
            "for_each_executed",
            action_name=action.name,
            loop_over=action.loop_over,
            iterations=iteration_count,
        )
        return {"iterations": iteration_count, "loop_over": action.loop_over}


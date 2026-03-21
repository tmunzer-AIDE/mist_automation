"""
Workflow executor service — graph-based execution engine.

Traverses the workflow graph (nodes + edges) from the trigger node,
executing each node and following edges based on output ports.
"""

import asyncio
import copy
import json
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from app.core.exceptions import WorkflowExecutionError, WorkflowTimeoutError
from app.modules.automation.models.execution import (
    ExecutionStatus,
    NodeExecutionResult,
    NodeSnapshot,
    WorkflowExecution,
)
from app.modules.automation.models.workflow import Workflow, WorkflowNode
from app.services.mist_service import MistService
from app.utils.variables import create_jinja_env, get_nested_value, strip_template_braces

logger = structlog.get_logger(__name__)


ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]] | None


def _sanitize_name(name: str) -> str:
    """Sanitize a node name for use as a variable key (non-alphanumeric → underscores)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


class WorkflowExecutor:
    """Graph-based workflow executor."""

    _jinja_env = create_jinja_env()

    def __init__(
        self,
        mist_service: MistService | None = None,
        progress_callback: ProgressCallback = None,
        recursion_depth: int = 0,
        max_recursion_depth: int = 5,
    ):
        self.mist_service = mist_service or MistService()
        self.variable_context: dict[str, Any] = {"trigger": {}, "nodes": {}, "results": {}}
        self._progress_callback = progress_callback
        self._cached_render_context: dict[str, Any] | None = None
        self._recursion_depth = recursion_depth
        self._max_recursion_depth = max_recursion_depth

    async def execute_workflow(
        self,
        workflow: Workflow,
        trigger_data: dict[str, Any],
        trigger_source: str = "webhook",
        execution: WorkflowExecution | None = None,
        simulate: bool = False,
        dry_run: bool = False,
    ) -> WorkflowExecution:
        """
        Execute a workflow graph.

        Args:
            workflow: Workflow to execute
            trigger_data: Trigger payload
            trigger_source: Source of trigger (webhook, cron, manual, simulation)
            execution: Optional pre-created execution record
            simulate: If True, capture snapshots for step-by-step replay
            dry_run: If True, mock external API calls
        """
        start_time = datetime.now(timezone.utc)

        if execution is None:
            execution = WorkflowExecution(
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                trigger_type=trigger_source or "manual",
                trigger_data=trigger_data,
                status=ExecutionStatus.RUNNING,
                is_simulation=simulate,
                is_dry_run=dry_run,
            )
            await execution.insert()
        else:
            execution.status = ExecutionStatus.RUNNING
            execution.is_simulation = simulate
            execution.is_dry_run = dry_run
            await execution.save()

        logger.info(
            "workflow_execution_started",
            workflow_id=str(workflow.id),
            execution_id=str(execution.id),
            trigger_source=trigger_source,
            simulate=simulate,
            dry_run=dry_run,
        )

        # Initialize variable context
        self.variable_context = {"trigger": trigger_data, "results": {}, "nodes": {}}

        try:
            execution = await asyncio.wait_for(
                self._execute_graph(workflow, execution, simulate=simulate, dry_run=dry_run),
                timeout=workflow.timeout_seconds,
            )

        except asyncio.TimeoutError:
            execution.status = ExecutionStatus.TIMEOUT
            execution.error = f"Workflow exceeded timeout of {workflow.timeout_seconds} seconds"
            execution.add_log(f"Workflow timed out after {workflow.timeout_seconds} seconds", "error")
            await execution.save()

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

            workflow.failure_count += 1
            workflow.last_execution = start_time
            workflow.last_failure = start_time
            await workflow.save()
            raise WorkflowExecutionError(f"Workflow execution failed: {e}")

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

    # ── Graph execution ──────────────────────────────────────────────────────

    async def _execute_graph(
        self,
        workflow: Workflow,
        execution: WorkflowExecution,
        simulate: bool = False,
        dry_run: bool = False,
    ) -> WorkflowExecution:
        """Execute the workflow graph via BFS from the entry node."""

        # Build adjacency map: source_node_id -> [(edge, target_node)]
        node_map = {n.id: n for n in workflow.nodes}
        adjacency: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for edge in workflow.edges:
            adjacency[edge.source_node_id].append((edge.source_port_id, edge.target_node_id, edge.target_port_id))

        # Find entry node (trigger for standard, subflow_input for sub-flows)
        entry_node = workflow.get_entry_node()
        if not entry_node:
            raise WorkflowExecutionError("No entry node found in workflow")

        is_subflow = workflow.workflow_type == "subflow"

        # Step 1: Evaluate trigger condition (skip for sub-flows)
        if not is_subflow:
            trigger_condition = entry_node.config.get("condition")
            if trigger_condition:
                execution.trigger_condition = trigger_condition
                execution.add_log(f"Evaluating trigger condition: {trigger_condition}")
                condition_passed = self._evaluate_condition_expression(trigger_condition)
                execution.trigger_condition_passed = condition_passed
                execution.add_log(f"Trigger condition result: {'passed' if condition_passed else 'not met'}")
                await execution.save()

                if not condition_passed:
                    execution.status = ExecutionStatus.FILTERED
                    execution.add_log("Workflow filtered out — trigger condition not met")
                    await execution.save()
                    return execution
            else:
                execution.trigger_condition_passed = True
                await execution.save()
        else:
            execution.trigger_condition_passed = True
            await execution.save()

        # Step 2: Extract trigger/input variables
        entry_save_as = entry_node.save_as
        if entry_save_as:
            self._store_save_as_variables(entry_save_as, self.variable_context.get("trigger", {}))

        # Record entry node snapshot
        step_counter = [0]
        if simulate:
            step_counter[0] += 1
            execution.node_snapshots.append(
                NodeSnapshot(
                    node_id=entry_node.id,
                    node_name=entry_node.name,
                    step=step_counter[0],
                    input_variables={},
                    output_data=self.variable_context.get("trigger", {}),
                    status="success",
                    variables_after=copy.deepcopy(self.variable_context),
                )
            )
            if self._progress_callback:
                await self._progress_callback(
                    "node_completed",
                    {
                        "node_id": entry_node.id,
                        "node_name": entry_node.name,
                        "step": step_counter[0],
                        "status": "success",
                        "duration_ms": None,
                        "error": None,
                        "output_data": self.variable_context.get("trigger", {}),
                    },
                )

        # Step 3: BFS traverse from entry node
        execution.add_log(f"Starting graph execution with {len(workflow.nodes)} nodes and {len(workflow.edges)} edges")
        await execution.save()

        all_success = await self._traverse_from(
            entry_node.id,
            adjacency,
            node_map,
            execution,
            dry_run=dry_run,
            simulate=simulate,
            step_counter=step_counter,
        )

        # Set final status
        if all_success:
            execution.status = ExecutionStatus.SUCCESS
        else:
            has_success = any(r.status == "success" for r in execution.node_results.values())
            execution.status = ExecutionStatus.PARTIAL if has_success else ExecutionStatus.FAILED

        execution.variables = self.variable_context.get("results", {})
        await execution.save()
        return execution

    async def _traverse_from(
        self,
        start_node_id: str,
        adjacency: dict[str, list[tuple[str, str, str]]],
        node_map: dict[str, WorkflowNode],
        execution: WorkflowExecution,
        dry_run: bool = False,
        simulate: bool = False,
        step_counter: list[int] | None = None,
        visited: set[str] | None = None,
        initial_port_filter: str | None = None,
    ) -> bool:
        """
        Traverse and execute nodes starting from a given node, following edges.
        Returns True if all nodes executed successfully.
        """
        if visited is None:
            visited = {start_node_id}  # trigger already "executed"
        if step_counter is None:
            step_counter = [0]

        all_success = True

        # Get downstream nodes from start
        initial_edges = adjacency.get(start_node_id, [])
        if initial_port_filter:
            initial_edges = [e for e in initial_edges if e[0] == initial_port_filter]
        queue = list(initial_edges)

        while queue:
            source_port_id, target_node_id, target_port_id = queue.pop(0)

            if target_node_id in visited:
                continue
            visited.add(target_node_id)

            node = node_map.get(target_node_id)
            if not node:
                continue

            if not node.enabled:
                execution.add_log(f"Node '{node.name or node.id}' skipped (disabled)")
                continue

            execution.add_log(f"Executing node '{node.name or node.id}' ({node.type})")

            # Capture input snapshot for simulation
            input_snapshot = copy.deepcopy(self.variable_context) if simulate else None

            # Broadcast node_started via progress callback
            if self._progress_callback:
                await self._progress_callback(
                    "node_started",
                    {"node_id": node.id, "node_name": node.name, "step": step_counter[0] + 1},
                )

            snapshot_recorded = False
            result: dict[str, Any] | None = None

            try:
                node_start = datetime.now(timezone.utc)
                result = await self._execute_node(node, execution, dry_run=dry_run, simulate=simulate)
                node_end = datetime.now(timezone.utc)
                node_duration_ms = int((node_end - node_start).total_seconds() * 1000)
                node_result = NodeExecutionResult(
                    node_id=node.id,
                    node_name=node.name,
                    node_type=node.type,
                    status="success",
                    started_at=node_start,
                    completed_at=node_end,
                    duration_ms=node_duration_ms,
                    output_data=result,
                    input_snapshot=input_snapshot,
                    retry_count=0,
                )
                execution.add_node_result(node_result)
                execution.add_log(f"Node '{node.name or node.id}' succeeded")

                # Store output in variable context and invalidate caches
                self.variable_context["nodes"][node.id] = result
                if node.name:
                    self.variable_context["nodes"][_sanitize_name(node.name)] = result
                self._invalidate_render_cache()

                # Handle save_as bindings
                if node.save_as and result:
                    self._store_save_as_variables(node.save_as, result)

                # For for_each nodes, record snapshot BEFORE entering loop body traversal
                # so the snapshot order is: ... → For Each → body nodes (not body nodes → For Each)
                if node.type == "for_each" and simulate:
                    step_counter[0] += 1
                    execution.node_snapshots.append(
                        NodeSnapshot(
                            node_id=node.id,
                            node_name=node.name,
                            step=step_counter[0],
                            input_variables=input_snapshot or {},
                            output_data=result,
                            status=node_result.status,
                            duration_ms=node_result.duration_ms,
                            error=node_result.error,
                            variables_after=copy.deepcopy(self.variable_context),
                        )
                    )
                    snapshot_recorded = True
                    if self._progress_callback:
                        await self._progress_callback(
                            "node_completed",
                            {
                                "node_id": node.id,
                                "node_name": node.name,
                                "step": step_counter[0],
                                "status": node_result.status,
                                "duration_ms": node_result.duration_ms,
                                "error": node_result.error,
                                "output_data": result,
                            },
                        )

                # Special handling for for_each — execute loop body subgraph per item
                if node.type == "for_each":
                    loop_body_edges = [e for e in adjacency.get(node.id, []) if e[0] == "loop_body"]
                    if loop_body_edges:
                        config = node.config
                        loop_over_raw = config.get("loop_over", "")
                        loop_over = strip_template_braces(loop_over_raw)
                        collection = get_nested_value(self.variable_context, loop_over) or []
                        max_iterations = config.get("max_iterations", 100)
                        items = collection[:max_iterations]
                        loop_variable = config.get("loop_variable", "item")
                        parallel = config.get("parallel", False)

                        collected_results: list[dict[str, Any]] = []

                        if parallel:
                            # ── Parallel iteration: isolated executor per item ────
                            max_concurrent = config.get("max_concurrent", 5)
                            sem = asyncio.Semaphore(max_concurrent)

                            async def _run_iteration(i: int, item: Any) -> tuple[bool, dict[str, Any]]:
                                async with sem:
                                    iter_executor = WorkflowExecutor(mist_service=self.mist_service)
                                    iter_executor.variable_context = copy.deepcopy(self.variable_context)
                                    iter_executor.variable_context["loop"] = {loop_variable: item, "index": i}
                                    iter_executor.variable_context["item"] = item
                                    item_output = item if isinstance(item, dict) else {"value": item}
                                    iter_executor.variable_context["nodes"][node.id] = item_output
                                    if node.name:
                                        iter_executor.variable_context["nodes"][_sanitize_name(node.name)] = item_output

                                    body_visited: set[str] = {node.id}
                                    success = await iter_executor._traverse_from(
                                        node.id,
                                        adjacency,
                                        node_map,
                                        execution,
                                        dry_run=dry_run,
                                        simulate=simulate,
                                        step_counter=step_counter,
                                        visited=body_visited,
                                        initial_port_filter="loop_body",
                                    )
                                    # Collect last body node output + iteration item
                                    last_output: dict[str, Any] = {}
                                    for nid in body_visited:
                                        if nid != node.id and nid in execution.node_results:
                                            last_output = execution.node_results[nid].output_data or {}
                                    return success, {"item": item, "output": last_output}

                            iteration_results = await asyncio.gather(
                                *[_run_iteration(i, item) for i, item in enumerate(items)],
                                return_exceptions=True,
                            )
                            for r in iteration_results:
                                if isinstance(r, Exception):
                                    all_success = False
                                else:
                                    success, entry = r
                                    collected_results.append(entry)
                                    if not success:
                                        all_success = False

                        else:
                            # ── Sequential iteration (default) ────────────────────
                            for i, item in enumerate(items):
                                self.variable_context["loop"] = {loop_variable: item, "index": i}
                                self.variable_context["item"] = item

                                item_output = item if isinstance(item, dict) else {"value": item}
                                self.variable_context["nodes"][node.id] = item_output
                                if node.name:
                                    self.variable_context["nodes"][_sanitize_name(node.name)] = item_output
                                self._invalidate_render_cache()

                                body_visited: set[str] = {node.id}
                                loop_success = await self._traverse_from(
                                    node.id,
                                    adjacency,
                                    node_map,
                                    execution,
                                    dry_run=dry_run,
                                    simulate=simulate,
                                    step_counter=step_counter,
                                    visited=body_visited,
                                    initial_port_filter="loop_body",
                                )

                                # Collect last body node output + iteration item
                                last_output: dict[str, Any] = {}
                                for nid in body_visited:
                                    if nid != node.id and nid in execution.node_results:
                                        last_output = execution.node_results[nid].output_data or {}
                                collected_results.append({"item": item, "output": last_output})

                                if not loop_success:
                                    all_success = False
                                    if not node.continue_on_error:
                                        break

                        # Clean up loop context and store aggregated results
                        self.variable_context.pop("loop", None)
                        self.variable_context.pop("item", None)
                        result = {
                            "iterations": len(items),
                            "loop_over": loop_over,
                            "results": collected_results,
                        }
                        self.variable_context["nodes"][node.id] = result
                        if node.name:
                            self.variable_context["nodes"][_sanitize_name(node.name)] = result
                        self._invalidate_render_cache()

                # Determine which edges to follow based on node type
                next_edges = self._resolve_output_edges(node, result, adjacency)
                for edge_info in next_edges:
                    if edge_info[1] not in visited:
                        queue.append(edge_info)

            except Exception as e:
                node_result = NodeExecutionResult(
                    node_id=node.id,
                    node_name=node.name,
                    node_type=node.type,
                    status="failed",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    error=str(e),
                    input_snapshot=input_snapshot,
                )
                execution.add_node_result(node_result)
                execution.add_log(f"Node '{node.name or node.id}' failed: {e}", "error")
                logger.error("node_execution_failed", node_id=node.id, error=str(e))

                all_success = False
                if not node.continue_on_error:
                    execution.add_log(
                        f"Stopping workflow — node '{node.name or node.id}' failed and continue_on_error is off",
                        "warning",
                    )
                    break

                # Even on failure with continue_on_error, follow "default" edges
                for edge_info in adjacency.get(node.id, []):
                    if edge_info[0] == "default" and edge_info[1] not in visited:
                        queue.append(edge_info)

            # Record simulation snapshot (skip if already recorded for for_each)
            if simulate and not snapshot_recorded:
                step_counter[0] += 1
                execution.node_snapshots.append(
                    NodeSnapshot(
                        node_id=node.id,
                        node_name=node.name,
                        step=step_counter[0],
                        input_variables=input_snapshot or {},
                        output_data=result if node_result.status == "success" else None,
                        status=node_result.status,
                        duration_ms=node_result.duration_ms,
                        error=node_result.error,
                        variables_after=copy.deepcopy(self.variable_context),
                    )
                )
                if self._progress_callback:
                    await self._progress_callback(
                        "node_completed",
                        {
                            "node_id": node.id,
                            "node_name": node.name,
                            "step": step_counter[0],
                            "status": node_result.status,
                            "duration_ms": node_result.duration_ms,
                            "error": node_result.error,
                            "output_data": result if node_result.status == "success" else None,
                        },
                    )

            await execution.save()

        return all_success

    def _resolve_output_edges(
        self,
        node: WorkflowNode,
        result: dict[str, Any] | None,
        adjacency: dict[str, list[tuple[str, str, str]]],
    ) -> list[tuple[str, str, str]]:
        """Determine which edges to follow based on node type and execution result."""
        all_edges = adjacency.get(node.id, [])

        if node.type == "condition" and result:
            # Follow the matching branch edge
            matched = result.get("matched_branch")
            if matched is None:
                return []
            if matched == "else":
                return [e for e in all_edges if e[0] == "else"]
            return [e for e in all_edges if e[0] == f"branch_{matched}"]

        if node.type == "for_each":
            # For-each: the loop body is handled internally,
            # only follow the "done" edge after loop completes
            return [e for e in all_edges if e[0] == "done"]

        # Default: follow all "default" edges
        return [e for e in all_edges if e[0] == "default"]

    # ── Node execution ───────────────────────────────────────────────────────

    async def _execute_node(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        dry_run: bool = False,
        simulate: bool = False,
    ) -> dict[str, Any]:
        """Execute a single node with retry logic."""
        last_error = None

        for attempt in range(node.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info("node_retry", node_id=node.id, attempt=attempt)
                    await asyncio.sleep(node.retry_delay)

                return await self._execute_node_by_type(node, execution, dry_run=dry_run, simulate=simulate)

            except Exception as e:
                last_error = e
                logger.warning("node_attempt_failed", node_id=node.id, attempt=attempt, error=str(e))

        raise last_error  # type: ignore[misc]

    async def _execute_node_by_type(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        dry_run: bool = False,
        simulate: bool = False,
    ) -> dict[str, Any]:
        """Dispatch node execution based on type."""
        node_type = node.type
        config = node.config

        if node_type in ("mist_api_get", "mist_api_post", "mist_api_put", "mist_api_delete"):
            method = node_type.replace("mist_api_", "").upper()
            if dry_run:
                return await self._mock_mist_api(method, config)
            return await self._execute_mist_api(method, config)

        if node_type == "webhook":
            if dry_run:
                return {
                    "status": "mocked",
                    "url": config.get("webhook_url", ""),
                    "auth_type": config.get("webhook_auth_type", "none"),
                }
            return await self._execute_webhook(config)

        if node_type == "delay":
            seconds = config.get("delay_seconds", 1)
            if not dry_run:
                await asyncio.sleep(seconds)
            return {"delayed_seconds": seconds}

        if node_type == "condition":
            return await self._execute_condition(node, execution, dry_run=dry_run)

        if node_type == "set_variable":
            return await self._execute_set_variable(config)

        if node_type == "for_each":
            return await self._execute_for_each(node, execution, dry_run=dry_run)

        if node_type == "data_transform":
            return await self._execute_data_transform(config)

        if node_type == "format_report":
            return await self._execute_format_report(config)

        if node_type == "servicenow":
            if dry_run:
                return {
                    "status": "mocked",
                    "instance_url": config.get("servicenow_instance_url", ""),
                    "method": config.get("servicenow_method", "POST"),
                    "table": config.get("servicenow_table", "incident"),
                }
            return await self._execute_servicenow(config)

        if node_type in ("slack", "pagerduty", "email"):
            if dry_run:
                return {"status": "mocked", "channel": config.get("notification_channel", "")}
            return await self._execute_notification(node_type, config)

        if node_type == "invoke_subflow":
            return await self._execute_invoke_subflow(node, execution, dry_run=dry_run, simulate=simulate)

        if node_type == "subflow_output":
            return await self._execute_subflow_output(config)

        if node_type == "device_utils":
            if dry_run:
                return {
                    "status": "mocked",
                    "device_type": config.get("device_type", ""),
                    "function": config.get("function", ""),
                    "data": [],
                }
            return await self._execute_device_utils(config)

        if node_type == "ai_agent":
            if dry_run:
                return {
                    "status": "mocked",
                    "task": config.get("agent_task", ""),
                    "iterations": 0,
                    "tool_calls": [],
                }
            return await self._execute_ai_agent(node, execution)

        raise NotImplementedError(f"Node type '{node_type}' not implemented")

    # ── TLS ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_verify() -> str | bool:
        """Return the TLS verify option, respecting CA_CERT_PATH for proxies like ZScaler.

        Returns CA_CERT_PATH if configured, otherwise uses system CA store (True).
        Only disable verification explicitly via environment configuration.
        """
        import os

        from app.config import settings

        if settings.ca_cert_path and os.path.isfile(settings.ca_cert_path):
            return settings.ca_cert_path
        return True

    # ── Template rendering ───────────────────────────────────────────────────

    def _invalidate_render_cache(self) -> None:
        """Invalidate the cached render context (call after each node execution)."""
        self._cached_render_context = None

    def _build_render_context(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Build a Jinja2 rendering context from the full variable context.

        Includes trigger, results, nodes, loop/item,
        and utility values (now, now_iso, etc.). Uses cached base context when possible.
        """
        if self._cached_render_context is None:
            context: dict[str, Any] = {}

            # Add trigger data at root level (for {{ topic }}, {{ events }}) AND under "trigger" key
            trigger_data = self.variable_context.get("trigger")
            if trigger_data:
                context.update(trigger_data)
                context["trigger"] = trigger_data

            # Add saved results
            results = self.variable_context.get("results")
            if results:
                for key, value in results.items():
                    context[key] = value

            # Node names are already sanitized (spaces → underscores) at storage time
            context["nodes"] = self.variable_context.get("nodes", {})

            # Add loop context
            if "loop" in self.variable_context:
                context["loop"] = self.variable_context["loop"]
            if "item" in self.variable_context:
                context["item"] = self.variable_context["item"]

            self._cached_render_context = context

        # Utility values are always fresh (time-dependent)
        result = {**self._cached_render_context}
        now = datetime.now(timezone.utc)
        result["now"] = now
        result["now_iso"] = now.isoformat()
        result["now_timestamp"] = int(now.timestamp())

        if extra:
            result.update(extra)

        return result

    def _render_template(self, template: str) -> str:
        """Render a Jinja2 template using the full variable context."""
        if not template:
            return template

        context = self._build_render_context()

        try:
            return self._jinja_env.from_string(template).render(context)
        except Exception as e:
            raise ValueError(f"Template syntax error at line 1: {e}") from e

    def _render_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively render Jinja2 templates in a dictionary's string values."""
        result: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self._render_template(value)
            elif isinstance(value, dict):
                result[key] = self._render_dict(value)
            elif isinstance(value, list):
                result[key] = self._render_list(value)
            else:
                result[key] = value
        return result

    def _render_list(self, data: list) -> list:
        """Recursively render Jinja2 templates in a list's string items."""
        result: list = []
        for item in data:
            if isinstance(item, str):
                result.append(self._render_template(item))
            elif isinstance(item, dict):
                result.append(self._render_dict(item))
            elif isinstance(item, list):
                result.append(self._render_list(item))
            else:
                result.append(item)
        return result

    # ── Action implementations ───────────────────────────────────────────────

    async def _execute_mist_api(self, method: str, config: dict) -> dict[str, Any]:
        """Execute a Mist API call.

        Returns a dict with ``status_code`` and ``body`` keys so templates
        can access the response uniformly via ``{{ nodes.Name.body.field }}``.
        """
        endpoint = self._render_template(config.get("api_endpoint", ""))
        params = self._render_dict(config.get("api_params", {}) or {})

        if method in ("POST", "PUT"):
            body = self._render_dict(config.get("api_body", {}) or {})
            data = await getattr(self.mist_service, f"api_{method.lower()}")(endpoint, body)
        elif method == "DELETE":
            await self.mist_service.api_delete(endpoint, params)
            data = {"status": "deleted"}
        else:
            data = await self.mist_service.api_get(endpoint, params)

        logger.info(f"mist_api_{method.lower()}_executed", endpoint=endpoint)
        return {"status_code": 200, "body": data}

    async def _mock_mist_api(self, method: str, config: dict) -> dict[str, Any]:
        """Generate a mock response for a Mist API call using OAS."""
        from app.modules.automation.services.oas_service import OASService

        endpoint = self._render_template(config.get("api_endpoint", ""))
        oas_endpoint = OASService.get_endpoint(method, endpoint)

        if oas_endpoint:
            return {
                "status_code": 200,
                "body": OASService.generate_mock_response(oas_endpoint),
            }

        return {"status_code": 200, "body": {"mocked": True}}

    async def _execute_webhook(self, config: dict) -> dict[str, Any]:
        """Execute webhook action with optional OAuth 2.0 token acquisition."""
        url = self._render_template(config.get("webhook_url", ""))

        from app.utils.url_safety import validate_outbound_url

        validate_outbound_url(url)

        headers = self._render_dict(config.get("webhook_headers", {}) or {})
        body = self._render_dict(config.get("webhook_body", {}) or {})

        # OAuth 2.0 Password Grant — acquire bearer token
        if config.get("webhook_auth_type") == "oauth2_password":
            token = await self._acquire_oauth2_token(config)
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=30.0, verify=self._resolve_verify()) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()

        logger.info("webhook_executed", url=url, status_code=response.status_code)
        return {"status_code": response.status_code, "response": response.text[:1000]}

    async def _execute_servicenow(self, config: dict) -> dict[str, Any]:
        """Execute ServiceNow API action with method selection and OAuth/basic auth."""
        from app.config import settings
        from app.utils.url_safety import validate_outbound_url

        method = (config.get("servicenow_method") or "POST").upper()
        instance_url = (
            config.get("servicenow_instance_url")
            or config.get("notification_channel")  # backward compat
            or settings.servicenow_instance_url
            or ""
        )
        table = config.get("servicenow_table") or "incident"
        custom_path = config.get("servicenow_path")

        if custom_path:
            endpoint = f"{instance_url.rstrip('/')}/{custom_path.lstrip('/')}"
        else:
            endpoint = f"{instance_url.rstrip('/')}/api/now/table/{table}"

        endpoint = self._render_template(endpoint)
        validate_outbound_url(endpoint)

        body = self._render_dict(config.get("servicenow_body", {}) or {})
        query_params = self._render_dict(config.get("servicenow_query_params", {}) or {})

        # Auth dispatch
        auth_type = config.get("servicenow_auth_type", "basic")
        auth = None
        extra_headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}

        if auth_type == "oauth2_password":
            token = await self._acquire_oauth2_token(config)
            extra_headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            from app.modules.automation.services.oauth_secrets import decrypt_node_secrets

            secrets = decrypt_node_secrets(config)
            username = secrets.get("servicenow_username") or settings.servicenow_username or ""
            password = secrets.get("servicenow_password") or settings.servicenow_password or ""
            if username and password:
                auth = (username, password)

        async with httpx.AsyncClient(timeout=30.0, verify=self._resolve_verify()) as client:
            kwargs: dict[str, Any] = {"headers": extra_headers}
            if auth:
                kwargs["auth"] = auth
            if method in ("POST", "PUT", "PATCH") and body:
                kwargs["json"] = body
            if method == "GET" and query_params:
                kwargs["params"] = query_params

            response = await client.request(method, endpoint, **kwargs)
            response.raise_for_status()

        logger.info("servicenow_executed", endpoint=endpoint, method=method, status_code=response.status_code)
        return {"status_code": response.status_code, "response": response.text[:1000]}

    async def _acquire_oauth2_token(self, config: dict) -> str:
        """Acquire an OAuth 2.0 access token using the Password Grant (ROPC).

        Credentials are decrypted from the node config. The token URL is
        SSRF-validated. Credentials are NOT Jinja2-rendered to prevent
        leaking secrets into the template context.
        """
        from app.modules.automation.services.oauth_secrets import decrypt_node_secrets
        from app.utils.url_safety import validate_outbound_url

        secrets = decrypt_node_secrets(config)

        token_url = secrets.get("oauth2_token_url", "")
        if not token_url:
            raise WorkflowExecutionError("OAuth2 token URL is required")
        validate_outbound_url(token_url)

        client_id = secrets.get("oauth2_client_id", "")
        client_secret = secrets.get("oauth2_client_secret", "")
        username = secrets.get("oauth2_username", "")
        password = secrets.get("oauth2_password", "")

        if not all((client_id, client_secret, username, password)):
            raise WorkflowExecutionError("OAuth2 credentials are incomplete")

        async with httpx.AsyncClient(timeout=15.0, verify=self._resolve_verify()) as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()

        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise WorkflowExecutionError("OAuth2 token response missing access_token")

        logger.info("oauth2_token_acquired", token_url=token_url)
        return access_token

    async def _execute_device_utils(self, config: dict) -> dict[str, Any]:
        """Execute a mistapi.device_utils diagnostic command.

        Calls the appropriate device utility function (ping, traceroute, ARP, etc.)
        and awaits the WebSocket-streamed results via UtilResponse.
        """
        from mistapi.device_utils import ap, ex, srx, ssr

        from app.modules.automation.device_utils_catalog import is_allowed

        device_type = self._render_template(config.get("device_type", ""))
        func_name = self._render_template(config.get("function", ""))
        site_id = self._render_template(config.get("site_id", ""))
        device_id = self._render_template(config.get("device_id", ""))

        if not all((device_type, func_name, site_id, device_id)):
            raise WorkflowExecutionError("device_utils requires device_type, function, site_id, device_id")

        if not is_allowed(device_type, func_name):
            raise WorkflowExecutionError(f"device_utils: '{device_type}.{func_name}' is not an allowed operation")

        modules = {"ap": ap, "ex": ex, "srx": srx, "ssr": ssr}
        module = modules.get(device_type)
        if module is None:
            raise WorkflowExecutionError(f"device_utils: unknown device type '{device_type}'")

        func = getattr(module, func_name, None)
        if func is None:
            raise WorkflowExecutionError(f"device_utils: unknown function '{func_name}' on '{device_type}'")

        # Build function-specific kwargs from config params
        params: dict[str, Any] = {}
        for key, val in (config.get("params", {}) or {}).items():
            if val is not None and val != "":
                rendered = self._render_template(str(val)) if isinstance(val, str) else val
                # List-typed params (e.g., port_ids): split comma-separated strings into lists
                if isinstance(rendered, str) and key.endswith("_ids"):
                    params[key] = [s.strip() for s in rendered.split(",")]
                else:
                    params[key] = rendered

        try:
            response = func(self.mist_service.get_session(), site_id, device_id, **params)
            await response  # UtilResponse.__await__() — waits for WS completion
        except WorkflowExecutionError:
            raise
        except Exception as e:
            logger.error("device_utils_failed", device_type=device_type, function=func_name, error=str(e))
            raise WorkflowExecutionError(f"Device utility '{device_type}.{func_name}' failed") from e

        status_code = response.trigger_api_response.status_code if response.trigger_api_response else None
        logger.info("device_utils_executed", device_type=device_type, function=func_name, site_id=site_id)
        return {
            "status": "success",
            "device_type": device_type,
            "function": func_name,
            "data": response.ws_data,
        }

    async def _execute_ai_agent(
        self, node: WorkflowNode, execution: WorkflowExecution
    ) -> dict[str, Any]:
        """Execute an AI agent node: LLM + MCP tool-calling loop."""
        from app.modules.llm.services.agent_service import AIAgentService
        from app.modules.llm.services.llm_service_factory import create_llm_service
        from app.modules.llm.services.mcp_client import MCPClientWrapper, MCPServerConfig

        config = node.config
        task = self._render_template(config.get("agent_task", ""))
        system_prompt = self._render_template(config.get("agent_system_prompt", ""))
        max_iterations = min(int(config.get("max_iterations", 10)), 25)
        mcp_configs = config.get("mcp_servers", [])

        if not task:
            raise WorkflowExecutionError("AI agent task is empty")

        llm = await create_llm_service()

        # Connect to configured MCP servers (validate URLs, then connect in parallel)
        from app.utils.url_safety import validate_outbound_url

        for srv in mcp_configs:
            validate_outbound_url(srv.get("url", ""))

        pending = [
            MCPClientWrapper(MCPServerConfig(
                name=srv.get("name", "unnamed"),
                url=srv.get("url", ""),
                headers=srv.get("headers") or None,
                ssl_verify=srv.get("ssl_verify", True),
            ))
            for srv in mcp_configs
        ]
        clients = pending
        try:
            await asyncio.gather(*(c.connect() for c in clients))

            agent = AIAgentService(llm=llm, mcp_clients=clients, max_iterations=max_iterations)
            result = await agent.run(
                task=task,
                system_prompt=system_prompt,
                context=self.variable_context,
            )

            execution.add_log(f"AI agent completed: {result.status} ({result.iterations} iterations)")
            return result.to_dict()

        finally:
            for client in clients:
                await client.disconnect()

    def _build_slack_message_blocks(self, config: dict, message: str) -> list[dict[str, Any]] | None:
        """Assemble Slack Block Kit blocks from node config + upstream data.

        Returns None if no blocks are needed (fall back to legacy attachments).
        """
        blocks: list[dict[str, Any]] = []

        # 1. Header block
        header = self._render_template(config.get("slack_header", ""))
        if header.strip():
            blocks.append({"type": "header", "text": {"type": "plain_text", "text": header[:150]}})

        # 2. Section block with message text (skip if message looks like raw JSON blocks)
        if message.strip() and not message.strip().startswith("[{"):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": message[:3000]}})

        # 3. Section block with key-value fields
        fields_config = config.get("slack_fields", [])
        if fields_config:
            rendered_fields = []
            for f in fields_config:
                label = self._render_template(f.get("label", ""))
                value = self._render_template(f.get("value", ""))
                if label.strip():
                    rendered_fields.append({"type": "mrkdwn", "text": f"*{label}*\n{value}"})
            if rendered_fields:
                blocks.append({"type": "section", "fields": rendered_fields[:10]})

        # 4. Auto-detected table blocks from upstream format_report
        for node_output in self.variable_context.get("nodes", {}).values():
            if isinstance(node_output, dict) and isinstance(node_output.get("slack_blocks"), list):
                blocks.extend(node_output["slack_blocks"])
                break

        # 4.5 JSON payload block (if configured)
        json_path = config.get("slack_json_variable", "").strip()
        if json_path.startswith("{{"):
            json_path = json_path.lstrip("{").rstrip("}").strip()
        if json_path:
            resolved = get_nested_value(self._build_render_context(), json_path)
            if resolved is not None:
                blocks.extend(self._build_slack_json_block(resolved))

        # 5. Footer as context block
        footer = self._render_template(config.get("slack_footer", ""))
        if footer.strip():
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})

        return blocks if blocks else None

    async def _execute_invoke_subflow(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        dry_run: bool = False,
        simulate: bool = False,
    ) -> dict[str, Any]:
        """Execute an invoke_subflow node — runs a sub-flow workflow as a child execution."""
        from beanie import PydanticObjectId

        config = node.config

        # Check recursion depth
        if self._recursion_depth >= self._max_recursion_depth:
            raise WorkflowExecutionError(f"Maximum sub-flow recursion depth ({self._max_recursion_depth}) exceeded")

        # Fetch target workflow
        target_wf_id = config.get("target_workflow_id")
        if not target_wf_id:
            raise WorkflowExecutionError("invoke_subflow node missing target_workflow_id")

        try:
            target_workflow = await Workflow.get(PydanticObjectId(target_wf_id))
        except Exception as e:
            raise WorkflowExecutionError(f"Invalid target workflow ID: {target_wf_id}") from e

        if not target_workflow:
            raise WorkflowExecutionError(f"Target sub-flow workflow not found: {target_wf_id}")

        if target_workflow.workflow_type != "subflow":
            raise WorkflowExecutionError(f"Target workflow '{target_workflow.name}' is not a sub-flow")

        # Resolve input mappings
        input_mappings: dict[str, str] = config.get("input_mappings", {})
        resolved_inputs: dict[str, Any] = {}

        for param in target_workflow.input_parameters:
            if param.name in input_mappings:
                template = input_mappings[param.name]
                resolved_inputs[param.name] = self._render_template(template)
            elif param.required:
                if param.default_value is not None:
                    resolved_inputs[param.name] = param.default_value
                else:
                    raise WorkflowExecutionError(f"Required sub-flow input parameter '{param.name}' not provided")
            elif param.default_value is not None:
                resolved_inputs[param.name] = param.default_value

        # Create child execution
        child_execution = WorkflowExecution(
            workflow_id=target_workflow.id,
            workflow_name=target_workflow.name,
            trigger_type="subflow",
            trigger_data=resolved_inputs,
            status=ExecutionStatus.PENDING,
            is_simulation=simulate,
            is_dry_run=dry_run,
            parent_execution_id=execution.id,
            parent_workflow_id=execution.workflow_id,
        )
        await child_execution.insert()

        # Create child executor with incremented recursion depth
        child_executor = WorkflowExecutor(
            mist_service=self.mist_service,
            progress_callback=self._progress_callback,
            recursion_depth=self._recursion_depth + 1,
            max_recursion_depth=self._max_recursion_depth,
        )

        try:
            child_execution = await child_executor.execute_workflow(
                workflow=target_workflow,
                trigger_data=resolved_inputs,
                trigger_source="subflow",
                execution=child_execution,
                simulate=simulate,
                dry_run=dry_run,
            )
        except Exception as e:
            execution.add_log(f"Sub-flow '{target_workflow.name}' failed: {e}", "error")
            raise WorkflowExecutionError(f"Sub-flow '{target_workflow.name}' execution failed: {e}") from e

        # Link child execution to parent
        execution.child_execution_ids.append(child_execution.id)

        # Extract outputs from child execution variables
        output = child_execution.variables or {}

        execution.add_log(f"Sub-flow '{target_workflow.name}' completed with status {child_execution.status.value}")

        if child_execution.status not in (ExecutionStatus.SUCCESS, ExecutionStatus.PARTIAL):
            raise WorkflowExecutionError(
                f"Sub-flow '{target_workflow.name}' finished with status: {child_execution.status.value}"
            )

        return {
            "child_execution_id": str(child_execution.id),
            "child_workflow_id": str(target_workflow.id),
            "child_workflow_name": target_workflow.name,
            "status": child_execution.status.value,
            "outputs": output,
        }

    async def _execute_subflow_output(self, config: dict) -> dict[str, Any]:
        """Execute a subflow_output node — renders output expressions and stores them."""
        outputs_config: dict[str, str] = config.get("outputs", {})
        rendered_outputs: dict[str, Any] = {}

        for key, template in outputs_config.items():
            rendered_outputs[key] = self._render_template(template)

        # Store outputs in the results context so they appear in execution.variables
        for key, value in rendered_outputs.items():
            self.variable_context["results"][key] = value

        return rendered_outputs

    async def _execute_notification(self, node_type: str, config: dict) -> dict[str, Any]:
        """Execute a notification action (slack, servicenow, pagerduty)."""
        from app.services.notification_service import NotificationService

        template = config.get("notification_template", "")
        message = self._render_template(template)
        channel = config.get("notification_channel", "")

        async with NotificationService() as ns:
            if node_type == "slack":
                blocks = self._build_slack_message_blocks(config, message)
                return await ns.send_slack_notification(webhook_url=channel, message=message, blocks=blocks)
            elif node_type == "pagerduty":
                return await ns.send_pagerduty_alert(
                    integration_key=channel,
                    summary=message,
                    severity=config.get("severity", "warning"),
                )
            elif node_type == "email":
                recipients = [r.strip() for r in channel.split(",")]
                subject = self._render_template(config.get("email_subject", "Workflow Notification"))
                html = config.get("email_html", False)
                return await ns.send_email(to=recipients, subject=subject, body=message, html=html)
            else:
                logger.warning(f"Unknown notification type: {node_type}")
                return {"status": "unsupported", "type": node_type}

    async def _execute_condition(
        self, node: WorkflowNode, execution: WorkflowExecution, dry_run: bool = False
    ) -> dict[str, Any]:
        """Execute a condition node — evaluate branches, return which matched."""
        branches = node.config.get("branches", [])

        for i, branch in enumerate(branches):
            condition_expr = branch.get("condition", "")
            if self._evaluate_condition_expression(condition_expr):
                logger.info("condition_branch_matched", node_id=node.id, branch_index=i)
                return {"matched_branch": i, "condition": condition_expr}

        # Check for else
        if node.config.get("else_actions"):
            logger.info("condition_else_branch", node_id=node.id)
            return {"matched_branch": "else"}

        logger.info("condition_no_match", node_id=node.id)
        return {"matched_branch": None}

    async def _execute_set_variable(self, config: dict) -> dict[str, Any]:
        """Execute a set_variable node."""
        expression = config.get("variable_expression", "")
        rendered = self._render_template(expression).strip()

        try:
            value = json.loads(rendered)
        except (json.JSONDecodeError, ValueError):
            value = rendered

        var_name = config.get("variable_name", "unnamed")
        self.variable_context["results"][var_name] = value
        logger.info("set_variable_executed", variable_name=var_name, value=str(value)[:200])
        return {"variable_name": var_name, "value": value}

    async def _execute_for_each(
        self, node: WorkflowNode, execution: WorkflowExecution, dry_run: bool = False
    ) -> dict[str, Any]:
        """Validate the for_each collection. Actual iteration is handled by _traverse_from."""
        config = node.config
        loop_over_raw = config.get("loop_over", "")
        # Strip Jinja2 template braces if present (e.g. "{{ trigger.events }}" → "trigger.events")
        loop_over = strip_template_braces(loop_over_raw)
        collection = get_nested_value(self.variable_context, loop_over)

        if collection is None:
            raise ValueError(f"for_each: '{loop_over}' resolved to None")
        if not isinstance(collection, list):
            raise ValueError(f"for_each: '{loop_over}' is not a list (got {type(collection).__name__})")

        max_iterations = config.get("max_iterations", 100)
        iteration_count = min(len(collection), max_iterations)

        logger.info("for_each_executed", node_id=node.id, iterations=iteration_count)
        return {"iterations": iteration_count, "loop_over": loop_over, "results": []}

    # ── Data processing ────────────────────────────────────────────────────

    async def _execute_data_transform(self, config: dict) -> dict[str, Any]:
        """Extract and filter fields from a data array."""
        source_raw = config.get("source", "")
        source = strip_template_braces(source_raw)
        collection = get_nested_value(self.variable_context, source)

        if collection is None:
            raise ValueError(f"data_transform: '{source}' resolved to None")
        if not isinstance(collection, list):
            if isinstance(collection, dict):
                collection = [collection]
            else:
                raise ValueError(f"data_transform: '{source}' is not a list (got {type(collection).__name__})")

        fields = config.get("fields", [])
        if not fields:
            raise ValueError("data_transform: no fields specified")

        filter_expr = config.get("filter", "")

        # Build column definitions
        seen_keys: dict[str, int] = {}
        columns: list[dict[str, str]] = []
        for field in fields:
            path = field.get("path", "").strip()
            label = field.get("label", "")
            # Strip {{ }} wrappers and pipe/filter for key derivation
            if path.startswith("{{"):
                path = path[2:]
            if path.endswith("}}"):
                path = path[:-2]
            dot_path = path.split("|")[0].strip() if "|" in path else path.strip()
            key = dot_path.split(".")[-1] if dot_path else ""
            if key in seen_keys:
                seen_keys[key] += 1
                key = f"{key}_{seen_keys[key]}"
            else:
                seen_keys[key] = 0
            columns.append({"key": key, "label": label or key})

        rows: list[dict[str, Any]] = []
        for item in collection:
            # Apply optional filter
            if filter_expr:
                ctx = self._build_render_context(extra={"item": item})
                rendered = self._jinja_env.from_string(filter_expr).render(ctx).strip()
                if rendered.lower() in ("", "false", "0", "none", "null", "undefined"):
                    continue

            # Extract fields (supports pipe filters: "path.to.field | datetimeformat")
            row: dict[str, Any] = {}
            for i, field in enumerate(fields):
                raw_path = field.get("path", "").strip()
                col_key = columns[i]["key"]

                # Strip {{ }} wrappers if present
                if raw_path.startswith("{{"):
                    raw_path = raw_path[2:]
                if raw_path.endswith("}}"):
                    raw_path = raw_path[:-2]
                raw_path = raw_path.strip()

                if "|" in raw_path:
                    dot_path, filter_expr = raw_path.split("|", 1)
                    raw_value = self._get_nested_field(item, dot_path.strip())
                    try:
                        tpl = self._jinja_env.from_string(f"{{{{ value | {filter_expr.strip()} }}}}")
                        value = tpl.render(value=raw_value)
                    except Exception:
                        value = raw_value
                else:
                    value = self._get_nested_field(item, raw_path)

                row[col_key] = value
            rows.append(row)

        logger.info("data_transform_executed", source=source, rows=len(rows), columns=len(columns))
        return {"rows": rows, "columns": columns, "row_count": len(rows)}

    @staticmethod
    def _get_nested_field(data: Any, path: str) -> Any:
        """Traverse a nested dict/object by dot-separated path."""
        cursor = data
        for segment in path.split("."):
            if isinstance(cursor, dict) and segment in cursor:
                cursor = cursor[segment]
            else:
                return None
        return cursor

    async def _execute_format_report(self, config: dict) -> dict[str, Any]:
        """Format structured data as a table report."""
        # Resolve rows
        data_source_raw = config.get("data_source", "")
        data_source = strip_template_braces(data_source_raw)
        rows = get_nested_value(self.variable_context, data_source)

        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError(f"format_report: data_source is not a list (got {type(rows).__name__})")

        # Resolve column defs
        columns: list[dict[str, str]] | None = None
        columns_source_raw = config.get("columns_source", "")
        if columns_source_raw:
            cs = strip_template_braces(columns_source_raw)
            columns = get_nested_value(self.variable_context, cs)

        # Auto-detect from first row
        if not columns and rows:
            columns = [{"key": k, "label": k} for k in rows[0].keys()]
        if not columns:
            columns = []

        fmt = config.get("format", "markdown")

        # Render title/footer
        title = self._render_template(config.get("title", "")) if config.get("title") else ""
        footer = self._render_template(config.get("footer_template", "")) if config.get("footer_template") else ""

        # Format the table
        report = self._format_table(rows, columns, fmt)

        # Add title/footer
        if title:
            if fmt == "markdown":
                report = f"## {title}\n\n{report}"
            else:
                report = f"{title}\n\n{report}"
        if footer:
            report = f"{report}\n\n{footer}"

        result: dict[str, Any] = {"report": report, "format": fmt, "row_count": len(rows)}

        # For slack format, also build Block Kit blocks
        if fmt == "slack":
            result["slack_blocks"] = self._build_slack_table_blocks(rows, columns, title, footer)

        logger.info("format_report_executed", format=fmt, rows=len(rows))
        return result

    @staticmethod
    def _format_table(rows: list[dict], columns: list[dict[str, str]], fmt: str) -> str:
        """Format rows+columns into the requested table format."""
        if not columns:
            return ""

        col_keys = [c["key"] for c in columns]
        col_labels = [c["label"] for c in columns]

        if fmt == "csv":
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(col_labels)
            for row in rows:
                writer.writerow([str(row.get(k, "")) for k in col_keys])
            return output.getvalue().strip()

        # Compute column widths for aligned formats
        widths = [len(label) for label in col_labels]
        str_rows: list[list[str]] = []
        for row in rows:
            str_row = [str(row.get(k, "")) for k in col_keys]
            for i, cell in enumerate(str_row):
                widths[i] = max(widths[i], len(cell))
            str_rows.append(str_row)

        if fmt == "markdown":
            header = "| " + " | ".join(label.ljust(widths[i]) for i, label in enumerate(col_labels)) + " |"
            separator = "| " + " | ".join("-" * widths[i] for i in range(len(columns))) + " |"
            lines = [header, separator]
            for str_row in str_rows:
                line = "| " + " | ".join(str_row[i].ljust(widths[i]) for i in range(len(columns))) + " |"
                lines.append(line)
            return "\n".join(lines)

        if fmt == "slack":
            lines = []
            header = "  ".join(label.ljust(widths[i]) for i, label in enumerate(col_labels))
            lines.append(header)
            lines.append("-" * len(header))
            for str_row in str_rows:
                line = "  ".join(str_row[i].ljust(widths[i]) for i in range(len(columns)))
                lines.append(line)
            return "\n".join(lines)

        # "text" or fallback
        lines = []
        header = "  ".join(label.ljust(widths[i]) for i, label in enumerate(col_labels))
        lines.append(header)
        lines.append("  ".join("-" * widths[i] for i in range(len(columns))))
        for str_row in str_rows:
            line = "  ".join(str_row[i].ljust(widths[i]) for i in range(len(columns)))
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _build_slack_table_blocks(
        rows: list[dict],
        columns: list[dict[str, str]],
        title: str = "",
        footer: str = "",
    ) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks with a preformatted table.

        Uses rich_text with rich_text_preformatted (monospace code block)
        which is supported by incoming webhooks and preserves column alignment.
        """
        if not columns:
            return []

        blocks: list[dict[str, Any]] = []

        if title:
            blocks.append({"type": "header", "text": {"type": "plain_text", "text": title[:150]}})

        # Build aligned text table and wrap in a rich_text preformatted block
        table_text = WorkflowExecutor._format_table(rows[:99], columns, "slack")
        if table_text:
            blocks.append(
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_preformatted",
                            "elements": [{"type": "text", "text": table_text}],
                        }
                    ],
                }
            )

        if footer:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": footer}],
                }
            )

        return blocks

    @staticmethod
    def _build_slack_json_block(data: Any) -> list[dict[str, Any]]:
        """Wrap arbitrary data as a pretty-printed JSON code block for Slack."""
        MAX_LEN = 2990
        try:
            text = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(data)
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN] + "\n… (truncated)"
        return [
            {
                "type": "rich_text",
                "elements": [{"type": "rich_text_preformatted", "elements": [{"type": "text", "text": text}]}],
            }
        ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _evaluate_condition_expression(self, expression: str) -> bool:
        """Evaluate a Jinja2 condition expression using the full variable context."""
        context = self._build_render_context()
        rendered = self._jinja_env.from_string(expression).render(context).strip()
        return rendered.lower() not in ("", "false", "0", "none", "null", "undefined")

    def _store_save_as_variables(self, bindings: list, output: dict[str, Any]) -> None:
        """Store variables extracted from node output via save_as bindings."""
        for binding in bindings:
            if not binding.expression:
                self.variable_context["results"][binding.name] = output
            else:
                context = self._build_render_context(extra={"output": output})
                rendered = self._jinja_env.from_string(binding.expression).render(context).strip()

                try:
                    value = json.loads(rendered)
                except (json.JSONDecodeError, ValueError):
                    value = rendered

                self.variable_context["results"][binding.name] = value
                logger.debug("save_as_variable_stored", name=binding.name, value=str(value)[:200])

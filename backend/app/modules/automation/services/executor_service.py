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
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
import structlog
from app.core.exceptions import WorkflowExecutionError, WorkflowTimeoutError
from app.modules.automation.models.execution import (
    ExecutionStatus,
    NodeExecutionResult,
    NodeSnapshot,
    WorkflowExecution,
)
from app.modules.automation.models.workflow import ActionType, Workflow, WorkflowNode
from app.services.mist_service import MistService
from app.utils.variables import create_jinja_env, get_nested_value

logger = structlog.get_logger(__name__)


ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]] | None


class WorkflowExecutor:
    """Graph-based workflow executor."""

    _jinja_env = create_jinja_env()

    def __init__(self, mist_service: MistService | None = None, progress_callback: ProgressCallback = None):
        self.mist_service = mist_service or MistService()
        self.variable_context: dict[str, Any] = {}
        self._progress_callback = progress_callback

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
        """Execute the workflow graph via BFS from the trigger node."""

        # Build adjacency map: source_node_id -> [(edge, target_node)]
        node_map = {n.id: n for n in workflow.nodes}
        adjacency: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for edge in workflow.edges:
            adjacency[edge.source_node_id].append(
                (edge.source_port_id, edge.target_node_id, edge.target_port_id)
            )

        # Find trigger node
        trigger_node = workflow.get_trigger_node()
        if not trigger_node:
            raise WorkflowExecutionError("No trigger node found in workflow")

        # Step 1: Evaluate trigger condition
        trigger_condition = trigger_node.config.get("condition")
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

        # Step 2: Extract trigger variables
        trigger_save_as = trigger_node.save_as
        if trigger_save_as:
            self._store_save_as_variables(trigger_save_as, self.variable_context.get("trigger", {}))

        # Record trigger node snapshot
        step_counter = [0]
        if simulate:
            step_counter[0] += 1
            execution.node_snapshots.append(
                NodeSnapshot(
                    node_id=trigger_node.id,
                    node_name=trigger_node.name,
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
                        "node_id": trigger_node.id,
                        "node_name": trigger_node.name,
                        "step": step_counter[0],
                        "status": "success",
                        "duration_ms": None,
                        "error": None,
                        "output_data": self.variable_context.get("trigger", {}),
                    },
                )

        # Step 3: BFS traverse from trigger
        execution.add_log(f"Starting graph execution with {len(workflow.nodes)} nodes and {len(workflow.edges)} edges")
        await execution.save()

        all_success = await self._traverse_from(
            trigger_node.id,
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

            try:
                node_start = datetime.now(timezone.utc)
                result = await self._execute_node(node, execution, dry_run=dry_run)
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

                # Store output in variable context
                self.variable_context["nodes"][node.id] = result
                if node.name:
                    self.variable_context["nodes"][node.name] = result

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
                        loop_over = loop_over_raw.strip()
                        if loop_over.startswith("{{") and loop_over.endswith("}}"):
                            loop_over = loop_over[2:-2].strip()
                        collection = get_nested_value(self.variable_context, loop_over) or []
                        max_iterations = config.get("max_iterations", 100)
                        items = collection[:max_iterations]
                        loop_variable = config.get("loop_variable", "item")

                        for i, item in enumerate(items):
                            self.variable_context["loop"] = {loop_variable: item, "index": i}
                            self.variable_context["item"] = item

                            # Expose the current item as the node's output so downstream
                            # nodes can access fields via nodes.<for_each_name>.<field>
                            item_output = item if isinstance(item, dict) else {"value": item}
                            self.variable_context["nodes"][node.id] = item_output
                            if node.name:
                                self.variable_context["nodes"][node.name] = item_output

                            # Traverse loop body with fresh visited set each iteration
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
                            if not loop_success:
                                all_success = False
                                if not node.continue_on_error:
                                    break

                        # Clean up loop context and restore metadata as node output
                        self.variable_context.pop("loop", None)
                        self.variable_context.pop("item", None)
                        self.variable_context["nodes"][node.id] = result
                        if node.name:
                            self.variable_context["nodes"][node.name] = result

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
    ) -> dict[str, Any]:
        """Execute a single node with retry logic."""
        last_error = None

        for attempt in range(node.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info("node_retry", node_id=node.id, attempt=attempt)
                    await asyncio.sleep(node.retry_delay)

                return await self._execute_node_by_type(node, execution, dry_run=dry_run)

            except Exception as e:
                last_error = e
                logger.warning("node_attempt_failed", node_id=node.id, attempt=attempt, error=str(e))

        raise last_error  # type: ignore[misc]

    async def _execute_node_by_type(
        self,
        node: WorkflowNode,
        execution: WorkflowExecution,
        dry_run: bool = False,
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
                return {"status": "mocked", "url": config.get("webhook_url", "")}
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

        if node_type in ("slack", "servicenow", "pagerduty", "email"):
            if dry_run:
                return {"status": "mocked", "channel": config.get("notification_channel", "")}
            return await self._execute_notification(node_type, config)

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

    def _build_render_context(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Build a Jinja2 rendering context from the full variable context.

        Includes trigger, results, nodes (with sanitized name aliases), loop/item,
        and utility values (now, now_iso, etc.).
        """
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

        # Add nodes with sanitized name aliases (spaces → underscores)
        nodes = self.variable_context.get("nodes", {})
        sanitized_nodes: dict[str, Any] = {}
        for key, value in nodes.items():
            sanitized_nodes[key] = value
            sanitized = key.replace(" ", "_")
            if sanitized != key:
                sanitized_nodes[sanitized] = value
        context["nodes"] = sanitized_nodes

        # Add loop context
        if "loop" in self.variable_context:
            context["loop"] = self.variable_context["loop"]
        if "item" in self.variable_context:
            context["item"] = self.variable_context["item"]

        # Utility values
        from datetime import datetime, timezone as tz

        context["now"] = datetime.now(tz.utc)
        context["now_iso"] = datetime.now(tz.utc).isoformat()
        context["now_timestamp"] = int(datetime.now(tz.utc).timestamp())

        if extra:
            context.update(extra)

        return context

    def _normalize_template(self, template: str) -> str:
        """
        Pre-process a template to convert node name references with spaces
        into bracket notation that Jinja2 can parse.

        Converts:  {{ nodes.For Each Events.site_id }}
        To:        {{ nodes["For Each Events"]["site_id"] }}
        """
        if "nodes." not in template:
            return template

        # Collect node names that contain spaces (sorted longest-first to avoid partial matches)
        nodes = self.variable_context.get("nodes", {})
        names_with_spaces = sorted(
            [name for name in nodes if " " in name],
            key=len,
            reverse=True,
        )
        if not names_with_spaces:
            return template

        for name in names_with_spaces:
            # Match  nodes.<name>  optionally followed by  .<field>.<subfield>...
            # Use re.escape to handle any special regex chars in node names
            pattern = re.compile(
                r"nodes\." + re.escape(name) + r"((?:\.\w+)*)"
            )

            # Escape quotes in the node name to prevent bracket-notation injection
            safe_name = name.replace("\\", "\\\\").replace('"', '\\"')

            def _replace(m: re.Match, _safe=safe_name) -> str:
                suffix = m.group(1)  # e.g. ".site_id" or ".foo.bar" or ""
                parts = [f'["{seg}"]' for seg in suffix.split(".") if seg]
                return f'nodes["{_safe}"]' + "".join(parts)

            template = pattern.sub(_replace, template)

        return template

    def _render_template(self, template: str) -> str:
        """Render a Jinja2 template using the full variable context."""
        if not template:
            return template

        template = self._normalize_template(template)
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
        """Execute webhook action."""
        url = self._render_template(config.get("webhook_url", ""))
        headers = self._render_dict(config.get("webhook_headers", {}) or {})
        body = self._render_dict(config.get("webhook_body", {}) or {})

        async with httpx.AsyncClient(timeout=30.0, verify=self._resolve_verify()) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()

        logger.info("webhook_executed", url=url, status_code=response.status_code)
        return {"status_code": response.status_code, "response": response.text[:1000]}

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

        # 5. Footer as context block
        footer = self._render_template(config.get("slack_footer", ""))
        if footer.strip():
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})

        return blocks if blocks else None

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
            elif node_type == "servicenow":
                return await ns.send_servicenow_notification(
                    instance_url=channel,
                    username=config.get("servicenow_username"),
                    password=config.get("servicenow_password"),
                    short_description=message,
                )
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
        loop_over = loop_over_raw.strip()
        if loop_over.startswith("{{") and loop_over.endswith("}}"):
            loop_over = loop_over[2:-2].strip()
        collection = get_nested_value(self.variable_context, loop_over)

        if collection is None:
            raise ValueError(f"for_each: '{loop_over}' resolved to None")
        if not isinstance(collection, list):
            raise ValueError(f"for_each: '{loop_over}' is not a list (got {type(collection).__name__})")

        max_iterations = config.get("max_iterations", 100)
        iteration_count = min(len(collection), max_iterations)

        logger.info("for_each_executed", node_id=node.id, iterations=iteration_count)
        return {"iterations": iteration_count, "loop_over": loop_over}

    # ── Data processing ────────────────────────────────────────────────────

    async def _execute_data_transform(self, config: dict) -> dict[str, Any]:
        """Extract and filter fields from a data array."""
        source_raw = config.get("source", "")
        source = source_raw.strip()
        if source.startswith("{{") and source.endswith("}}"):
            source = source[2:-2].strip()
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
        data_source = data_source_raw.strip()
        if data_source.startswith("{{") and data_source.endswith("}}"):
            data_source = data_source[2:-2].strip()
        rows = get_nested_value(self.variable_context, data_source)

        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError(f"format_report: data_source is not a list (got {type(rows).__name__})")

        # Resolve column defs
        columns: list[dict[str, str]] | None = None
        columns_source_raw = config.get("columns_source", "")
        if columns_source_raw:
            cs = columns_source_raw.strip()
            if cs.startswith("{{") and cs.endswith("}}"):
                cs = cs[2:-2].strip()
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
            blocks.append({
                "type": "rich_text",
                "elements": [{
                    "type": "rich_text_preformatted",
                    "elements": [{"type": "text", "text": table_text}],
                }],
            })

        if footer:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": footer}],
            })

        return blocks

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

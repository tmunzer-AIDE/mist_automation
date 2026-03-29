"""
Workflow tool — consolidated workflow operations with action dispatch.

Actions: detail, execution_detail, create, update.
"""

from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from app.modules.mcp_server.helpers import elicit_confirmation, to_json
from app.modules.mcp_server.server import mcp, mcp_user_id_var

# Node types whose configs may contain encrypted OAuth / auth secrets
_OAUTH_NODE_TYPES = {"webhook", "servicenow"}


def _encrypt_nodes(
    new_nodes: list,
    existing_nodes: list | None = None,
) -> None:
    """Encrypt sensitive fields in OAuth-capable nodes before persisting."""
    from app.modules.automation.services.oauth_secrets import encrypt_node_secrets, merge_node_secrets

    existing_map: dict[str, dict] = {}
    if existing_nodes:
        existing_map = {n.id: n.config for n in existing_nodes if n.type in _OAUTH_NODE_TYPES}

    for node in new_nodes:
        if node.type in _OAUTH_NODE_TYPES:
            if node.id in existing_map:
                merge_node_secrets(node.config, existing_map[node.id])
            encrypt_node_secrets(node.config)


@mcp.tool()
async def workflow(
    ctx: Context,
    action: Annotated[
        str,
        Field(
            description=(
                "The workflow operation to perform. One of:\n"
                "- 'detail': Get workflow info (name, description, status, node/edge summary, "
                "execution stats, and last 5 executions). Requires: workflow_id.\n"
                "- 'execution_detail': Get a specific execution's results with per-node status, "
                "errors, durations, and log tail. Requires: execution_id.\n"
                "- 'create': Create a new workflow graph (saved as draft). Validates the graph first. "
                "Asks user for confirmation. Requires: name, nodes. Optional: description, edges, workflow_type.\n"
                "- 'update': Update an existing workflow's name, description, or graph. "
                "Validates then asks user for confirmation. Requires: workflow_id plus at least one of "
                "name, description, nodes, edges."
            ),
        ),
    ],
    workflow_id: Annotated[
        str,
        Field(
            description="Workflow MongoDB ID. Used by action='detail' and action='update'. Get this from search results."
        ),
    ] = "",
    execution_id: Annotated[
        str,
        Field(
            description="Execution MongoDB ID. Used by action='execution_detail'. Get this from workflow detail's recent_executions or from search(type='executions')."
        ),
    ] = "",
    name: Annotated[
        str,
        Field(description="Workflow name. Required for action='create', optional for action='update'."),
    ] = "",
    description: Annotated[
        str,
        Field(description="Workflow description text. Optional for action='create' and action='update'."),
    ] = "",
    nodes: Annotated[
        list[dict] | None,
        Field(
            description="List of workflow graph nodes. Each node: {id, type, name, position: {x, y}, config: {...}}. Required for action='create', optional for action='update'."
        ),
    ] = None,
    edges: Annotated[
        list[dict] | None,
        Field(
            description="List of workflow graph edges. Each edge: {id, source_node_id, source_port_id, target_node_id, target_port_id}. Optional for action='create' and action='update'."
        ),
    ] = None,
    workflow_type: Annotated[
        str,
        Field(
            description="Workflow type: 'standard' (trigger-based) or 'subflow' (callable from other workflows). Default: 'standard'."
        ),
    ] = "standard",
) -> str:
    """Manage automation workflows: inspect workflow details and execution history, or create/update workflow graphs.

    Use search(type='workflows') first to find workflows, then 'detail' to inspect one.
    Use search(type='executions') to find executions, then 'execution_detail' to see per-node results.
    """
    dispatchers: dict[str, Any] = {
        "detail": _detail,
        "execution_detail": _execution_detail,
        "create": _create,
        "update": _update,
    }

    handler = dispatchers.get(action)
    if not handler:
        return to_json({"error": f"Unknown action '{action}'. Use: {', '.join(dispatchers)}"})

    return await handler(
        ctx=ctx,
        workflow_id=workflow_id,
        execution_id=execution_id,
        name=name,
        description=description,
        nodes=nodes,
        edges=edges,
        workflow_type=workflow_type,
    )


async def _detail(*, workflow_id: str, **_kwargs) -> str:
    """Get workflow details with node summary and recent executions."""
    from beanie import PydanticObjectId

    from app.models.user import User
    from app.modules.automation.models.execution import WorkflowExecution
    from app.modules.automation.models.workflow import Workflow

    if not workflow_id:
        return to_json({"error": "workflow_id is required for action=detail"})

    try:
        wf = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception:
        return to_json({"error": f"Invalid workflow_id '{workflow_id}'"})

    if not wf:
        return to_json({"error": f"Workflow '{workflow_id}' not found"})

    # Access check — mirrors REST API's ownership/sharing filter
    user_id = mcp_user_id_var.get()
    if user_id:
        user = await User.get(PydanticObjectId(user_id))
        if user and not wf.can_be_accessed_by(user):
            return to_json({"error": "Access denied"})

    # Compact node summary (strip config, position, output_ports)
    node_summary = [{"id": n.id, "type": n.type, "name": n.name} for n in (wf.nodes or [])]

    # Last 5 executions
    recent = (
        await WorkflowExecution.find(
            WorkflowExecution.workflow_id == wf.id,
            WorkflowExecution.is_simulation == False,  # noqa: E712
        )
        .sort(-WorkflowExecution.started_at)
        .limit(5)
        .to_list()
    )

    recent_list = [
        {
            "id": str(ex.id),
            "status": ex.status,
            "trigger_type": ex.trigger_type,
            "duration_ms": ex.duration_ms,
            "started_at": ex.started_at,
        }
        for ex in recent
    ]

    return to_json(
        {
            "id": str(wf.id),
            "name": wf.name,
            "description": wf.description,
            "status": wf.status.value if hasattr(wf.status, "value") else str(wf.status),
            "workflow_type": wf.workflow_type,
            "nodes": node_summary,
            "edges_count": len(wf.edges or []),
            "execution_count": wf.execution_count,
            "success_count": wf.success_count,
            "failure_count": wf.failure_count,
            "recent_executions": recent_list,
        }
    )


async def _execution_detail(*, execution_id: str, **_kwargs) -> str:
    """Get execution details with per-node results and log tail."""
    from beanie import PydanticObjectId

    from app.modules.automation.models.execution import WorkflowExecution

    if not execution_id:
        return to_json({"error": "execution_id is required for action=execution_detail"})

    try:
        ex = await WorkflowExecution.get(PydanticObjectId(execution_id))
    except Exception:
        return to_json({"error": f"Invalid execution_id '{execution_id}'"})

    if not ex:
        return to_json({"error": f"Execution '{execution_id}' not found"})

    # Compact node results (strip output_data and input_snapshot)
    node_results = []
    for node_id, result in (ex.node_results or {}).items():
        node_results.append(
            {
                "node_id": node_id,
                "node_name": result.node_name,
                "node_type": result.node_type,
                "status": result.status,
                "duration_ms": result.duration_ms,
                "error": result.error,
            }
        )

    # Last 10 log lines
    logs = ex.logs or []
    logs_tail = logs[-10:] if len(logs) > 10 else logs

    return to_json(
        {
            "id": str(ex.id),
            "workflow_name": ex.workflow_name,
            "status": ex.status,
            "trigger_type": ex.trigger_type,
            "duration_ms": ex.duration_ms,
            "error": ex.error,
            "nodes_executed": ex.nodes_executed,
            "nodes_succeeded": ex.nodes_succeeded,
            "nodes_failed": ex.nodes_failed,
            "node_results": node_results,
            "logs_tail": logs_tail,
        }
    )


async def _create(
    *,
    ctx: Context,
    name: str,
    description: str,
    nodes: list[dict] | None,
    edges: list[dict] | None,
    workflow_type: str,
    **_kwargs,
) -> str:
    """Create a new workflow with graph validation and elicitation."""
    from beanie import PydanticObjectId

    from app.modules.automation.models.workflow import (
        Workflow,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
    )
    from app.modules.automation.services.graph_validator import validate_graph

    if not name:
        return to_json({"error": "name is required for action=create"})
    if not nodes:
        return to_json({"error": "nodes are required for action=create"})

    from pydantic import ValidationError

    from app.models.user import User

    # Verify user context and role before proceeding
    user_id = mcp_user_id_var.get()
    if not user_id:
        return to_json({"error": "Access denied: user context not available"})

    user = await User.get(PydanticObjectId(user_id))
    if not user or not user.can_manage_workflows():
        return to_json({"error": "Access denied: automation role required"})

    # Parse and validate graph
    try:
        parsed_nodes = [WorkflowNode(**n) for n in nodes]
        parsed_edges = [WorkflowEdge(**e) for e in (edges or [])]
        validate_graph(parsed_nodes, parsed_edges, workflow_type=workflow_type)
    except ValidationError as ve:
        return to_json({"validation_errors": [str(ve)]})
    except Exception:
        return to_json({"error": "Graph validation failed"})

    # Circular subflow check (mirrors REST API)
    from app.modules.automation.services.graph_validator import validate_no_circular_subflow_references

    try:
        await validate_no_circular_subflow_references(None, parsed_nodes)
    except Exception:
        return to_json({"error": "Circular sub-flow reference detected"})

    # Encrypt OAuth/auth secrets before persisting (mirrors REST API)
    _encrypt_nodes(parsed_nodes)

    # Elicit confirmation
    await elicit_confirmation(ctx, f"Create workflow '{name}' with {len(nodes)} nodes?")

    wf = Workflow(
        name=name,
        description=description or "",
        workflow_type=workflow_type,
        created_by=user_id,
        status=WorkflowStatus.DRAFT,
        nodes=parsed_nodes,
        edges=parsed_edges,
    )
    await wf.insert()

    return to_json({"workflow_id": str(wf.id), "name": wf.name, "status": "draft", "message": "Workflow created."})


async def _update(
    *,
    ctx: Context,
    workflow_id: str,
    name: str,
    description: str,
    nodes: list[dict] | None,
    edges: list[dict] | None,
    **_kwargs,
) -> str:
    """Update an existing workflow with graph validation and elicitation."""
    from beanie import PydanticObjectId

    from app.modules.automation.models.workflow import (
        Workflow,
        WorkflowEdge,
        WorkflowNode,
    )
    from app.modules.automation.services.graph_validator import validate_graph

    if not workflow_id:
        return to_json({"error": "workflow_id is required for action=update"})

    try:
        wf = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception:
        return to_json({"error": f"Invalid workflow_id '{workflow_id}'"})

    if not wf:
        return to_json({"error": f"Workflow '{workflow_id}' not found"})

    # Enforce ownership/permission check (mirrors REST API)
    from app.models.user import User
    from app.modules.mcp_server.server import mcp_user_id_var

    user_id = mcp_user_id_var.get()
    if user_id:
        user = await User.get(PydanticObjectId(user_id))
        if not user or not wf.can_be_modified_by(user):
            return to_json({"error": "Access denied: you do not have permission to modify this workflow"})
    else:
        return to_json({"error": "Access denied: user context not available"})

    # Apply changes
    changes = []
    prev_nodes = list(wf.nodes) if nodes is not None else None  # snapshot for secrets merge
    if name:
        wf.name = name
        changes.append(f"name='{name}'")
    if description:
        wf.description = description
        changes.append("description updated")
    if nodes is not None:
        wf.nodes = [WorkflowNode(**n) for n in nodes]
        changes.append(f"{len(nodes)} nodes")
    if edges is not None:
        wf.edges = [WorkflowEdge(**e) for e in edges]
        changes.append(f"{len(edges)} edges")

    if not changes:
        return to_json({"error": "No changes provided"})

    # Validate graph
    wf_type = wf.workflow_type or "standard"
    try:
        validate_graph(wf.nodes, wf.edges, workflow_type=wf_type)
    except Exception:
        return to_json({"error": "Graph validation failed"})

    # Encrypt OAuth/auth secrets before persisting (mirrors REST API)
    if nodes is not None:
        _encrypt_nodes(wf.nodes, existing_nodes=prev_nodes)

    # Elicit confirmation
    await elicit_confirmation(ctx, f"Update workflow '{wf.name}'? Changes: {', '.join(changes)}")

    wf.update_timestamp()
    await wf.save()

    return to_json(
        {
            "workflow_id": str(wf.id),
            "name": wf.name,
            "status": wf.status.value if hasattr(wf.status, "value") else str(wf.status),
            "message": "Workflow updated.",
        }
    )

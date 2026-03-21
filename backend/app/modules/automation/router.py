"""
Workflow automation API endpoints — graph-based workflow model.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.tasks import create_background_task
from app.dependencies import require_automation_role
from app.models.user import User
from app.modules.automation.api_catalog import API_CATALOG
from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
from app.modules.automation.models.workflow import (
    SharingPermission,
    SubflowParameter,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from app.modules.automation.schemas.workflow import (
    InlineGraphRequest,
    SimulateRequest,
    SubflowSchemaResponse,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowUpdate,
)

router = APIRouter()
logger = structlog.get_logger(__name__)

# Track running simulation tasks for cancellation
_simulation_tasks: dict[str, asyncio.Task] = {}


# ── Node types whose configs may contain encrypted OAuth / auth secrets ────────
_OAUTH_NODE_TYPES = {"webhook", "servicenow"}


# ── Response construction helpers ─────────────────────────────────────────────


def _execution_summary(ex: dict) -> dict:
    """Convert an aggregation result dict to execution list item."""
    return {
        "id": str(ex["_id"]),
        "workflow_id": str(ex.get("workflow_id", "")),
        "workflow_name": ex.get("workflow_name", ""),
        "status": ex.get("status", "unknown"),
        "trigger_type": ex.get("trigger_type", ""),
        "started_at": ex.get("started_at"),
        "completed_at": ex.get("completed_at"),
        "duration_ms": ex.get("duration_ms"),
        "nodes_executed": ex.get("nodes_executed", 0),
        "nodes_succeeded": ex.get("nodes_succeeded", 0),
        "nodes_failed": ex.get("nodes_failed", 0),
        "is_simulation": ex.get("is_simulation", False),
    }


def _node_result_to_dict(r, full: bool = False) -> dict:
    """Convert a NodeExecutionResult to response dict."""
    d = {
        "node_id": r.node_id,
        "node_name": r.node_name,
        "node_type": r.node_type,
        "status": r.status,
        "duration_ms": r.duration_ms,
        "error": r.error,
        "output_data": r.output_data,
    }
    if full:
        d.update(
            {
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "input_snapshot": r.input_snapshot,
                "retry_count": r.retry_count,
            }
        )
    return d


def _snapshot_to_dict(s) -> dict:
    """Convert a NodeSnapshot to response dict."""
    return {
        "node_id": s.node_id,
        "node_name": s.node_name,
        "step": s.step,
        "input_variables": s.input_variables,
        "output_data": s.output_data,
        "status": s.status,
        "duration_ms": s.duration_ms,
        "error": s.error,
        "variables_after": s.variables_after,
    }


def _mask_workflow_secrets(wf: Workflow) -> None:
    """Mask sensitive fields in OAuth-capable nodes before returning to client."""
    from app.modules.automation.services.oauth_secrets import mask_node_secrets

    for node in wf.nodes:
        if node.type in _OAUTH_NODE_TYPES:
            mask_node_secrets(node.config)


def _encrypt_workflow_secrets(
    new_nodes: list[WorkflowNode],
    existing_nodes: list[WorkflowNode] | None = None,
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


def _workflow_to_response(wf: Workflow) -> WorkflowResponse:
    _mask_workflow_secrets(wf)
    return WorkflowResponse(
        id=str(wf.id),
        name=wf.name,
        description=wf.description,
        workflow_type=wf.workflow_type,
        created_by=str(wf.created_by),
        status=wf.status.value,
        sharing=wf.sharing.value,
        timeout_seconds=wf.timeout_seconds,
        nodes=[n.model_dump() for n in wf.nodes],
        edges=[e.model_dump() for e in wf.edges],
        viewport=wf.viewport,
        input_parameters=[p.model_dump() for p in wf.input_parameters],
        output_parameters=[p.model_dump() for p in wf.output_parameters],
        execution_count=wf.execution_count,
        success_count=wf.success_count,
        failure_count=wf.failure_count,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


@router.get("/workflows/api-catalog", tags=["Workflows"])
async def get_api_catalog(
    _current_user: User = Depends(require_automation_role),
):
    """Return the Mist API endpoint catalog for action autocomplete."""
    return [entry.model_dump() for entry in API_CATALOG]


@router.get("/workflows/device-utils-catalog", tags=["Workflows"])
async def get_device_utils_catalog(
    _current_user: User = Depends(require_automation_role),
):
    """Return the device utility catalog for device_utils action autocomplete."""
    from app.modules.automation.device_utils_catalog import DEVICE_UTILS_CATALOG

    return [entry.model_dump() for entry in DEVICE_UTILS_CATALOG]


@router.get("/workflows/event-pairs", tags=["Workflows"])
async def get_event_pairs(
    _current_user: User = Depends(require_automation_role),
):
    """Return the event pairs catalog for aggregated webhook trigger config."""
    from app.modules.automation.event_pairs import EVENT_PAIRS

    return EVENT_PAIRS


@router.get("/workflows", response_model=WorkflowListResponse, tags=["Workflows"])
async def list_workflows(
    skip: int = Query(0, ge=0, description="Number of workflows to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of workflows to return"),
    status_filter: str | None = Query(None, description="Filter by status"),
    workflow_type: str | None = Query(None, description="Filter by workflow type: standard or subflow"),
    current_user: User = Depends(require_automation_role),
):
    """List all workflows accessible to the current user."""
    query = {
        "$or": [
            {"created_by": current_user.id},
            {"sharing": {"$in": [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]}},
        ]
    }

    if status_filter:
        query["status"] = status_filter
    if workflow_type:
        query["workflow_type"] = workflow_type

    total = await Workflow.find(query).count()
    workflows = await Workflow.find(query).skip(skip).limit(limit).to_list()

    return WorkflowListResponse(workflows=[_workflow_to_response(wf) for wf in workflows], total=total)


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED, tags=["Workflows"])
async def create_workflow(
    workflow_data: WorkflowCreate,
    current_user: User = Depends(require_automation_role),
):
    """Create a new graph-based workflow."""
    # Parse nodes and edges
    nodes = [WorkflowNode(**n) for n in workflow_data.nodes]
    edges = [WorkflowEdge(**e) for e in workflow_data.edges]
    wf_type = workflow_data.workflow_type or "standard"

    # Validate graph structure
    from app.modules.automation.services.graph_validator import validate_graph

    validate_graph(nodes, edges, workflow_type=wf_type)

    # Validate circular sub-flow references
    from app.modules.automation.services.graph_validator import validate_no_circular_subflow_references

    await validate_no_circular_subflow_references(None, nodes)

    _encrypt_workflow_secrets(nodes)

    input_params = [SubflowParameter(**p) for p in workflow_data.input_parameters]
    output_params = [SubflowParameter(**p) for p in workflow_data.output_parameters]

    workflow = Workflow(
        name=workflow_data.name,
        description=workflow_data.description,
        workflow_type=wf_type,
        created_by=current_user.id,
        status=WorkflowStatus.DRAFT,
        timeout_seconds=workflow_data.timeout_seconds,
        nodes=nodes,
        edges=edges,
        viewport=workflow_data.viewport,
        input_parameters=input_params,
        output_parameters=output_params,
    )
    await workflow.insert()

    logger.info("workflow_created", workflow_id=str(workflow.id), user_id=str(current_user.id))
    return _workflow_to_response(workflow)


@router.post(
    "/workflows/{workflow_id}/duplicate",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Workflows"],
)
async def duplicate_workflow(
    workflow_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Duplicate an existing workflow."""
    import uuid

    try:
        source = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not source.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Build old→new node ID mapping
    id_map = {node.id: str(uuid.uuid4()) for node in source.nodes}

    # Copy nodes with new IDs
    nodes = []
    for node in source.nodes:
        data = node.model_dump()
        data["id"] = id_map[node.id]
        nodes.append(WorkflowNode(**data))

    # Copy edges with updated references
    edges = []
    for edge in source.edges:
        data = edge.model_dump()
        data["id"] = str(uuid.uuid4())
        data["source_node_id"] = id_map.get(edge.source_node_id, edge.source_node_id)
        data["target_node_id"] = id_map.get(edge.target_node_id, edge.target_node_id)
        edges.append(WorkflowEdge(**data))

    _encrypt_workflow_secrets(nodes)

    workflow = Workflow(
        name=f"{source.name} (copy)",
        description=source.description,
        workflow_type=source.workflow_type,
        created_by=current_user.id,
        status=WorkflowStatus.DRAFT,
        timeout_seconds=source.timeout_seconds,
        nodes=nodes,
        edges=edges,
        viewport=source.viewport,
        input_parameters=list(source.input_parameters),
        output_parameters=list(source.output_parameters),
    )
    await workflow.insert()

    logger.info(
        "workflow_duplicated",
        source_id=str(source.id),
        new_id=str(workflow.id),
        user_id=str(current_user.id),
    )
    return _workflow_to_response(workflow)


@router.get("/executions", tags=["Executions"])
async def list_all_executions(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    status_filter: str | None = Query(None, description="Filter by execution status"),
    trigger_type: str | None = Query(None, description="Filter by trigger type"),
    current_user: User = Depends(require_automation_role),
):
    """List all workflow executions across all workflows accessible to the current user."""
    # Only show executions for workflows the user can access
    accessible_wfs = await Workflow.find(
        {
            "$or": [
                {"created_by": current_user.id},
                {"sharing": {"$in": [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]}},
            ]
        }
    ).to_list()
    accessible_ids = [wf.id for wf in accessible_wfs]

    match: dict = {"workflow_id": {"$in": accessible_ids}}
    if status_filter:
        match["status"] = status_filter
    if trigger_type:
        match["trigger_type"] = trigger_type

    total = await WorkflowExecution.find(match).count()

    executions = await WorkflowExecution.aggregate(
        [
            {"$match": match},
            {"$sort": {"started_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 1,
                    "workflow_id": 1,
                    "workflow_name": 1,
                    "status": 1,
                    "trigger_type": 1,
                    "started_at": 1,
                    "completed_at": 1,
                    "duration_ms": 1,
                    "nodes_executed": 1,
                    "nodes_succeeded": 1,
                    "nodes_failed": 1,
                    "is_simulation": 1,
                }
            },
        ]
    ).to_list()

    return {
        "executions": [_execution_summary(ex) for ex in executions],
        "total": total,
    }


@router.post("/executions/{execution_id}/cancel", tags=["Executions"])
async def cancel_execution(
    execution_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Cancel a pending or running execution."""
    try:
        ex_oid = PydanticObjectId(execution_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID format") from exc

    execution = await WorkflowExecution.get(ex_oid)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    # Verify user can access the parent workflow
    workflow = await Workflow.get(execution.workflow_id)
    if not workflow or not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if execution.status not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel execution with status '{execution.status.value}'",
        )

    execution.mark_completed(ExecutionStatus.CANCELLED)
    execution.add_log("Execution cancelled by user", "info")
    await execution.save()

    logger.info("execution_cancelled", execution_id=execution_id, user_id=str(current_user.id))
    return {"status": execution.status.value, "message": "Execution cancelled"}


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse, tags=["Workflows"])
async def get_workflow(
    workflow_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Get workflow details by ID."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return _workflow_to_response(workflow)


@router.put("/workflows/{workflow_id}", response_model=WorkflowResponse, tags=["Workflows"])
async def update_workflow(
    workflow_id: str,
    workflow_data: WorkflowUpdate,
    current_user: User = Depends(require_automation_role),
):
    """Update workflow details."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_modified_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to update this workflow")

    if workflow_data.name is not None:
        workflow.name = workflow_data.name
    if workflow_data.description is not None:
        workflow.description = workflow_data.description
    if workflow_data.status is not None:
        workflow.status = WorkflowStatus(workflow_data.status)
    if workflow_data.timeout_seconds is not None:
        workflow.timeout_seconds = workflow_data.timeout_seconds
    if workflow_data.input_parameters is not None:
        workflow.input_parameters = [SubflowParameter(**p) for p in workflow_data.input_parameters]
    if workflow_data.output_parameters is not None:
        workflow.output_parameters = [SubflowParameter(**p) for p in workflow_data.output_parameters]
    if workflow_data.nodes is not None:
        nodes = [WorkflowNode(**n) for n in workflow_data.nodes]
        edges = [WorkflowEdge(**e) for e in (workflow_data.edges or [])]
        from app.modules.automation.services.graph_validator import validate_graph

        validate_graph(nodes, edges, workflow_type=workflow.workflow_type)

        from app.modules.automation.services.graph_validator import validate_no_circular_subflow_references

        await validate_no_circular_subflow_references(str(workflow.id), nodes)
        _encrypt_workflow_secrets(nodes, existing_nodes=workflow.nodes)
        workflow.nodes = nodes
        workflow.edges = edges
    if workflow_data.edges is not None and workflow_data.nodes is None:
        # Only edges updated — re-validate with existing nodes
        edges = [WorkflowEdge(**e) for e in workflow_data.edges]
        from app.modules.automation.services.graph_validator import validate_graph

        validate_graph(workflow.nodes, edges, workflow_type=workflow.workflow_type)
        workflow.edges = edges
    if workflow_data.viewport is not None:
        workflow.viewport = workflow_data.viewport

    workflow.update_timestamp()
    await workflow.save()

    logger.info("workflow_updated", workflow_id=str(workflow.id), user_id=str(current_user.id))
    return _workflow_to_response(workflow)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Workflows"])
async def delete_workflow(
    workflow_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Delete a workflow."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if str(workflow.created_by) != str(current_user.id) and not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the workflow owner or admin can delete it"
        )

    await workflow.delete()
    logger.info("workflow_deleted", workflow_id=str(workflow.id), user_id=str(current_user.id))
    return None


@router.get(
    "/workflows/{workflow_id}/subflow-schema",
    response_model=SubflowSchemaResponse,
    tags=["Workflows"],
)
async def get_subflow_schema(
    workflow_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Get the input/output parameter schema of a sub-flow workflow."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if workflow.workflow_type != "subflow":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow is not a sub-flow")

    return SubflowSchemaResponse(
        id=str(workflow.id),
        name=workflow.name,
        input_parameters=[p.model_dump() for p in workflow.input_parameters],
        output_parameters=[p.model_dump() for p in workflow.output_parameters],
    )


@router.post("/workflows/{workflow_id}/execute", tags=["Workflows"])
async def execute_workflow(
    workflow_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Manually execute a workflow."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if workflow.status != WorkflowStatus.ENABLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Workflow must be enabled to execute")

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        status=ExecutionStatus.PENDING,
        trigger_type="manual",
        triggered_by=current_user.id,
    )
    await execution.insert()

    logger.info(
        "workflow_execution_triggered",
        workflow_id=str(workflow.id),
        execution_id=str(execution.id),
        user_id=str(current_user.id),
    )

    async def _run_manual_execution(wf_id: str, ex_id: str) -> None:
        """Background task: actually execute the workflow."""
        wf = await Workflow.get(PydanticObjectId(wf_id))
        ex = await WorkflowExecution.get(PydanticObjectId(ex_id))
        if not wf or not ex:
            return
        from app.modules.automation.services.executor_service import WorkflowExecutor
        from app.services.mist_service_factory import create_mist_service

        try:
            mist_service = await create_mist_service()
        except Exception:
            mist_service = None
        executor = WorkflowExecutor(mist_service=mist_service)
        trigger_data = {"trigger_type": "manual", "triggered_at": datetime.now(timezone.utc).isoformat()}
        try:
            await executor.execute_workflow(
                workflow=wf,
                trigger_data=trigger_data,
                trigger_source="manual",
                execution=ex,
            )
        except Exception as e:
            logger.error("manual_execution_error", execution_id=ex_id, error=str(e))
            if ex.status in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
                from app.modules.automation.services.executor_service import _sanitize_execution_error

                ex.mark_completed(ExecutionStatus.FAILED, error=_sanitize_execution_error(e))
                ex.add_log("Manual execution failed", "error")
                await ex.save()

    create_background_task(
        _run_manual_execution(str(workflow.id), str(execution.id)),
        name=f"manual-exec-{execution.id}",
    )

    return {
        "execution_id": str(execution.id),
        "status": "queued",
        "message": "Workflow execution has been queued",
    }


@router.get("/workflows/{workflow_id}/executions", tags=["Workflows"])
async def list_workflow_executions(
    workflow_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_automation_role),
):
    """List execution history for a workflow."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    total = await WorkflowExecution.find(WorkflowExecution.workflow_id == workflow.id).count()

    # Use aggregation with projection to avoid fetching large fields
    # (node_results, node_snapshots, trigger_data, variables, logs)
    # that can be very large with for_each loop iterations.
    executions = await WorkflowExecution.aggregate(
        [
            {"$match": {"workflow_id": workflow.id}},
            {"$sort": {"started_at": -1}},
            {"$skip": skip},
            {"$limit": limit},
            {
                "$project": {
                    "_id": 1,
                    "workflow_id": 1,
                    "workflow_name": 1,
                    "status": 1,
                    "trigger_type": 1,
                    "started_at": 1,
                    "completed_at": 1,
                    "duration_ms": 1,
                    "nodes_executed": 1,
                    "nodes_succeeded": 1,
                    "nodes_failed": 1,
                    "is_simulation": 1,
                }
            },
        ]
    ).to_list()

    return {
        "executions": [_execution_summary(ex) for ex in executions],
        "total": total,
    }


@router.get("/workflows/{workflow_id}/executions/{execution_id}", tags=["Workflows"])
async def get_workflow_execution(
    workflow_id: str,
    execution_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Get full execution details including node results, logs, and variables."""
    try:
        wf_oid = PydanticObjectId(workflow_id)
        ex_oid = PydanticObjectId(execution_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format") from exc

    workflow = await Workflow.get(wf_oid)
    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    execution = await WorkflowExecution.get(ex_oid)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    if execution.workflow_id != wf_oid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Execution does not belong to this workflow"
        )

    return {
        "id": str(execution.id),
        "workflow_id": str(execution.workflow_id),
        "workflow_name": execution.workflow_name,
        "status": execution.status.value,
        "trigger_type": execution.trigger_type,
        "trigger_data": execution.trigger_data,
        "triggered_by": str(execution.triggered_by) if execution.triggered_by else None,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "duration_ms": execution.duration_ms,
        "trigger_condition_passed": execution.trigger_condition_passed,
        "trigger_condition": execution.trigger_condition,
        "nodes_executed": execution.nodes_executed,
        "nodes_succeeded": execution.nodes_succeeded,
        "nodes_failed": execution.nodes_failed,
        "node_results": {nid: _node_result_to_dict(r, full=True) for nid, r in execution.node_results.items()},
        "node_snapshots": [_snapshot_to_dict(s) for s in execution.node_snapshots],
        "is_simulation": execution.is_simulation,
        "is_dry_run": execution.is_dry_run,
        "parent_execution_id": str(execution.parent_execution_id) if execution.parent_execution_id else None,
        "parent_workflow_id": str(execution.parent_workflow_id) if execution.parent_workflow_id else None,
        "child_execution_ids": [str(cid) for cid in execution.child_execution_ids],
        "error": execution.error,
        "error_details": execution.error_details,
        "variables": execution.variables,
        "logs": execution.logs,
    }


# ── Variable autocomplete endpoints ──────────────────────────────────────────


@router.get("/workflows/{workflow_id}/available-variables/{node_id}", tags=["Workflows"])
async def get_available_variables(
    workflow_id: str,
    node_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Get variables available to a specific node from upstream nodes."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    from app.modules.automation.services.node_schema_service import get_available_variables as _get_vars

    return _get_vars(workflow, node_id)


@router.post("/workflows/available-variables/{node_id}", tags=["Workflows"])
async def compute_available_variables(
    node_id: str,
    body: InlineGraphRequest,
    current_user: User = Depends(require_automation_role),
):
    """Compute variables available to a node from an in-memory (unsaved) graph."""
    nodes = [WorkflowNode(**n) for n in body.nodes]
    edges = [WorkflowEdge(**e) for e in body.edges]

    workflow = Workflow(
        name="__inline__",
        nodes=nodes,
        edges=edges,
        created_by=current_user.id,
        input_parameters=[SubflowParameter(**p) for p in body.input_parameters],
    )

    from app.modules.automation.services.node_schema_service import get_available_variables as _get_vars

    return _get_vars(workflow, node_id)


@router.get("/workflows/endpoint-schema", tags=["Workflows"])
async def get_endpoint_schema(
    method: str = Query(..., description="HTTP method"),
    path: str = Query(..., description="API path template"),
    _current_user: User = Depends(require_automation_role),
):
    """Look up the response schema for a Mist API endpoint from the OAS."""
    from app.modules.automation.services.oas_service import OASService

    endpoint = OASService.get_endpoint(method, path)
    if not endpoint:
        return {"fields": [], "schema": {}, "example": None}

    return {
        "fields": OASService.get_response_fields(endpoint),
        "schema": endpoint.response_schema,
        "example": endpoint.response_example,
    }


# ── Simulation endpoints ─────────────────────────────────────────────────────


@router.post("/workflows/{workflow_id}/simulate", tags=["Workflows"])
async def simulate_workflow(
    workflow_id: str,
    request: SimulateRequest,
    current_user: User = Depends(require_automation_role),
):
    """Simulate a workflow execution with optional dry-run mode."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Determine trigger payload
    trigger_data = request.payload or {}

    if request.webhook_event_id:
        from app.modules.automation.models.webhook import WebhookEvent

        try:
            event = await WebhookEvent.get(PydanticObjectId(request.webhook_event_id))
        except Exception:
            event = None
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook event not found")
        trigger_data = event.payload

    # Wrap payload in aggregation structure for aggregated_webhook triggers
    trigger_node = workflow.get_trigger_node()
    if trigger_node and trigger_node.config.get("trigger_type") == "aggregated_webhook":
        raw_event = trigger_data
        trigger_data = {
            "aggregation": {
                "window_id": "simulation",
                "group_key": f"site:{raw_event.get('site_id', 'unknown')}",
                "event_count": 1,
                "window_seconds": trigger_node.config.get("window_seconds", 120),
                "window_start": datetime.now(timezone.utc).isoformat(),
                "window_end": datetime.now(timezone.utc).isoformat(),
                "site_id": raw_event.get("site_id", ""),
                "site_name": raw_event.get("site_name", ""),
            },
            "events": [raw_event],
            "first_event": raw_event,
            "last_event": raw_event,
        }

    # If stream_id is provided, run asynchronously with WS progress
    if request.stream_id:
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            status=ExecutionStatus.PENDING,
            trigger_type="simulation",
            trigger_data=trigger_data,
            triggered_by=current_user.id,
            is_simulation=True,
            is_dry_run=request.dry_run,
        )
        await execution.insert()

        stream_id = request.stream_id
        dry_run = request.dry_run

        async def _run_simulation(wf_id: str, ex_id: str) -> None:
            from app.core.websocket import ws_manager
            from app.modules.automation.services.executor_service import WorkflowExecutor
            from app.services.mist_service_factory import create_mist_service

            wf = await Workflow.get(PydanticObjectId(wf_id))
            ex = await WorkflowExecution.get(PydanticObjectId(ex_id))
            if not wf or not ex:
                return

            channel = f"simulation:{stream_id}"

            async def progress_callback(event_type: str, data: dict) -> None:
                await ws_manager.broadcast(channel, {"type": event_type, "data": data})

            try:
                mist_service = await create_mist_service()
            except Exception:
                mist_service = None

            try:
                executor = WorkflowExecutor(mist_service=mist_service, progress_callback=progress_callback)
                completed = await executor.execute_workflow(
                    workflow=wf,
                    trigger_data=trigger_data,
                    trigger_source="simulation",
                    execution=ex,
                    simulate=True,
                    dry_run=dry_run,
                )
                await ws_manager.broadcast(
                    channel,
                    {
                        "type": "simulation_completed",
                        "data": _build_simulation_result(completed),
                    },
                )
            except asyncio.CancelledError:
                ex = await WorkflowExecution.get(PydanticObjectId(ex_id))
                if ex and ex.status not in (ExecutionStatus.CANCELLED,):
                    ex.mark_completed(ExecutionStatus.CANCELLED)
                    ex.add_log("Simulation cancelled by user", "info")
                    await ex.save()
                await ws_manager.broadcast(
                    channel,
                    {
                        "type": "simulation_completed",
                        "data": {
                            "execution_id": ex_id,
                            "status": "cancelled",
                            "node_results": {},
                            "node_snapshots": [],
                            "variables": {},
                            "logs": ex.logs if ex else [],
                        },
                    },
                )
            except Exception as e:
                logger.error("simulation_error", execution_id=ex_id, error=str(e))
                from app.modules.automation.services.executor_service import _sanitize_execution_error

                safe_error = _sanitize_execution_error(e)
                ex = await WorkflowExecution.get(PydanticObjectId(ex_id))
                if ex and ex.status in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
                    ex.mark_completed(ExecutionStatus.FAILED, error=safe_error)
                    ex.add_log("Simulation failed", "error")
                    await ex.save()
                await ws_manager.broadcast(
                    channel,
                    {
                        "type": "simulation_completed",
                        "data": {
                            "execution_id": ex_id,
                            "status": "failed",
                            "error": safe_error,
                            "node_results": {},
                            "node_snapshots": [],
                            "variables": {},
                            "logs": [f"[ERROR] {safe_error}"],
                        },
                    },
                )
            finally:
                _simulation_tasks.pop(ex_id, None)

        task = create_background_task(
            _run_simulation(str(workflow.id), str(execution.id)),
            name=f"simulation-{execution.id}",
        )
        _simulation_tasks[str(execution.id)] = task

        return {"execution_id": str(execution.id), "status": "pending"}

    # Synchronous fallback (no stream_id)
    from app.modules.automation.services.executor_service import WorkflowExecutor
    from app.services.mist_service_factory import create_mist_service

    try:
        mist_service = await create_mist_service()
    except Exception:
        mist_service = None

    executor = WorkflowExecutor(mist_service=mist_service)
    execution = await executor.execute_workflow(
        workflow=workflow,
        trigger_data=trigger_data,
        trigger_source="simulation",
        simulate=True,
        dry_run=request.dry_run,
    )

    return _build_simulation_result(execution)


@router.post("/workflows/{workflow_id}/simulate/{execution_id}/cancel", tags=["Workflows"])
async def cancel_simulation(
    workflow_id: str,
    execution_id: str,
    current_user: User = Depends(require_automation_role),
):
    """Cancel a running simulation."""
    workflow = await Workflow.get(PydanticObjectId(workflow_id))
    if not workflow or not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    task = _simulation_tasks.get(execution_id)
    if task and not task.done():
        task.cancel()
        return {"status": "cancelling"}

    # Task already finished or not found — update DB status if still running
    execution = await WorkflowExecution.get(PydanticObjectId(execution_id))
    if execution and execution.status in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
        execution.mark_completed(ExecutionStatus.CANCELLED)
        execution.add_log("Simulation cancelled by user", "info")
        await execution.save()

    return {"status": "cancelled"}


def _build_simulation_result(execution: WorkflowExecution) -> dict:
    """Build the simulation result dict from an execution."""
    return {
        "execution_id": str(execution.id),
        "status": execution.status.value,
        "duration_ms": execution.duration_ms,
        "node_results": {nid: _node_result_to_dict(r) for nid, r in execution.node_results.items()},
        "node_snapshots": [_snapshot_to_dict(s) for s in execution.node_snapshots],
        "variables": execution.variables,
        "logs": execution.logs,
    }


@router.get("/workflows/{workflow_id}/sample-payloads", tags=["Workflows"])
async def get_sample_payloads(
    workflow_id: str,
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(require_automation_role),
):
    """Get recent webhook events matching the workflow's trigger type for simulation."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Find the trigger node
    trigger_node = workflow.get_trigger_node()
    if not trigger_node:
        return {"payloads": []}

    webhook_type = trigger_node.config.get("webhook_topic") or trigger_node.config.get("webhook_type", "")
    if not webhook_type:
        return {"payloads": []}

    event_type_filter = trigger_node.config.get("event_type_filter", "")

    from app.modules.automation.models.webhook import WebhookEvent

    query = WebhookEvent.find(WebhookEvent.webhook_type == webhook_type)
    if event_type_filter:
        query = WebhookEvent.find(
            WebhookEvent.webhook_type == webhook_type,
            WebhookEvent.event_type == event_type_filter,
        )
    events = await query.sort("-received_at").limit(limit).to_list()

    return {
        "payloads": [
            {
                "event_id": str(e.id),
                "timestamp": e.received_at,
                "topic": e.webhook_topic,
                "webhook_type": e.webhook_type,
                "event_type": e.event_type,
                "payload_preview": _truncate_payload(e.payload),
                "payload": e.payload,
            }
            for e in events
        ]
    }


def _truncate_payload(payload: dict, max_depth: int = 2) -> dict:
    """Truncate a payload dict for preview display."""
    if max_depth <= 0:
        return {"...": "truncated"}

    result = {}
    for key, value in list(payload.items())[:10]:
        if isinstance(value, dict):
            result[key] = _truncate_payload(value, max_depth - 1)
        elif isinstance(value, list):
            result[key] = f"[{len(value)} items]"
        elif isinstance(value, str) and len(value) > 100:
            result[key] = value[:100] + "..."
        else:
            result[key] = value
    return result

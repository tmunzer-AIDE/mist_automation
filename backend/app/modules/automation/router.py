"""
Workflow automation API endpoints — graph-based workflow model.
"""

from datetime import datetime, timezone

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.tasks import create_background_task
from app.dependencies import get_current_user_from_token
from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
from app.models.user import User
from app.modules.automation.models.workflow import Workflow, WorkflowNode, WorkflowEdge, WorkflowStatus, SharingPermission
from app.modules.automation.schemas.workflow import (
    SimulateRequest,
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowUpdate,
)
from app.modules.automation.api_catalog import API_CATALOG

router = APIRouter()
logger = structlog.get_logger(__name__)


def _workflow_to_response(wf: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=str(wf.id),
        name=wf.name,
        description=wf.description,
        created_by=str(wf.created_by),
        status=wf.status.value,
        sharing=wf.sharing.value,
        timeout_seconds=wf.timeout_seconds,
        nodes=[n.model_dump() for n in wf.nodes],
        edges=[e.model_dump() for e in wf.edges],
        viewport=wf.viewport,
        execution_count=wf.execution_count,
        success_count=wf.success_count,
        failure_count=wf.failure_count,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


@router.get("/workflows/api-catalog", tags=["Workflows"])
async def get_api_catalog(
    _current_user: User = Depends(get_current_user_from_token),
):
    """Return the Mist API endpoint catalog for action autocomplete."""
    return [entry.model_dump() for entry in API_CATALOG]


@router.get("/workflows", response_model=WorkflowListResponse, tags=["Workflows"])
async def list_workflows(
    skip: int = Query(0, ge=0, description="Number of workflows to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of workflows to return"),
    status_filter: str | None = Query(None, description="Filter by status"),
    current_user: User = Depends(get_current_user_from_token),
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

    total = await Workflow.find(query).count()
    workflows = await Workflow.find(query).skip(skip).limit(limit).to_list()

    return WorkflowListResponse(workflows=[_workflow_to_response(wf) for wf in workflows], total=total)


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED, tags=["Workflows"])
async def create_workflow(
    workflow_data: WorkflowCreate,
    current_user: User = Depends(get_current_user_from_token),
):
    """Create a new graph-based workflow."""
    # Parse nodes and edges
    nodes = [WorkflowNode(**n) for n in workflow_data.nodes]
    edges = [WorkflowEdge(**e) for e in workflow_data.edges]

    # Validate graph structure
    from app.modules.automation.services.graph_validator import validate_graph

    validate_graph(nodes, edges)

    workflow = Workflow(
        name=workflow_data.name,
        description=workflow_data.description,
        created_by=current_user.id,
        status=WorkflowStatus.DRAFT,
        timeout_seconds=workflow_data.timeout_seconds,
        nodes=nodes,
        edges=edges,
        viewport=workflow_data.viewport,
    )
    await workflow.insert()

    logger.info("workflow_created", workflow_id=str(workflow.id), user_id=str(current_user.id))
    return _workflow_to_response(workflow)


@router.get("/executions", tags=["Executions"])
async def list_all_executions(
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    status_filter: str | None = Query(None, description="Filter by execution status"),
    trigger_type: str | None = Query(None, description="Filter by trigger type"),
    _current_user: User = Depends(get_current_user_from_token),
):
    """List all workflow executions across all workflows."""
    match: dict = {}
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
        "executions": [
            {
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
            for ex in executions
        ],
        "total": total,
    }


@router.post("/executions/{execution_id}/cancel", tags=["Executions"])
async def cancel_execution(
    execution_id: str,
    _current_user: User = Depends(get_current_user_from_token),
):
    """Cancel a pending or running execution."""
    try:
        ex_oid = PydanticObjectId(execution_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID format") from exc

    execution = await WorkflowExecution.get(ex_oid)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    if execution.status not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel execution with status '{execution.status.value}'",
        )

    execution.mark_completed(ExecutionStatus.CANCELLED)
    execution.add_log("Execution cancelled by user", "info")
    await execution.save()

    logger.info("execution_cancelled", execution_id=execution_id, user_id=str(_current_user.id))
    return {"status": execution.status.value, "message": "Execution cancelled"}


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse, tags=["Workflows"])
async def get_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_from_token),
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
    current_user: User = Depends(get_current_user_from_token),
):
    """Update workflow details."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    if str(workflow.created_by) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the workflow owner can update it")

    if workflow_data.name is not None:
        workflow.name = workflow_data.name
    if workflow_data.description is not None:
        workflow.description = workflow_data.description
    if workflow_data.status is not None:
        workflow.status = WorkflowStatus(workflow_data.status)
    if workflow_data.timeout_seconds is not None:
        workflow.timeout_seconds = workflow_data.timeout_seconds
    if workflow_data.nodes is not None:
        nodes = [WorkflowNode(**n) for n in workflow_data.nodes]
        edges = [WorkflowEdge(**e) for e in (workflow_data.edges or [])]
        from app.modules.automation.services.graph_validator import validate_graph

        validate_graph(nodes, edges)
        workflow.nodes = nodes
        workflow.edges = edges
    if workflow_data.edges is not None and workflow_data.nodes is None:
        # Only edges updated — re-validate with existing nodes
        edges = [WorkflowEdge(**e) for e in workflow_data.edges]
        from app.modules.automation.services.graph_validator import validate_graph

        validate_graph(workflow.nodes, edges)
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
    current_user: User = Depends(get_current_user_from_token),
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


@router.post("/workflows/{workflow_id}/execute", tags=["Workflows"])
async def execute_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_from_token),
):
    """Manually execute a workflow."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

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
        from app.services.mist_service_factory import create_mist_service
        from app.modules.automation.services.executor_service import WorkflowExecutor

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
            if ex.status in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
                ex.mark_completed(ExecutionStatus.FAILED, error=str(e))
                ex.add_log(f"Manual execution error: {e}", "error")
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
    _current_user: User = Depends(get_current_user_from_token),
):
    """List execution history for a workflow."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

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
        "executions": [
            {
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
            for ex in executions
        ],
        "total": total,
    }


@router.get("/workflows/{workflow_id}/executions/{execution_id}", tags=["Workflows"])
async def get_workflow_execution(
    workflow_id: str,
    execution_id: str,
    _current_user: User = Depends(get_current_user_from_token),
):
    """Get full execution details including node results, logs, and variables."""
    try:
        wf_oid = PydanticObjectId(workflow_id)
        ex_oid = PydanticObjectId(execution_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID format") from exc

    execution = await WorkflowExecution.get(ex_oid)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    if execution.workflow_id != wf_oid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Execution does not belong to this workflow")

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
        "node_results": {
            nid: {
                "node_id": r.node_id,
                "node_name": r.node_name,
                "node_type": r.node_type,
                "status": r.status,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "output_data": r.output_data,
                "input_snapshot": r.input_snapshot,
                "retry_count": r.retry_count,
            }
            for nid, r in execution.node_results.items()
        },
        "node_snapshots": [
            {
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
            for s in execution.node_snapshots
        ],
        "is_simulation": execution.is_simulation,
        "is_dry_run": execution.is_dry_run,
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
    _current_user: User = Depends(get_current_user_from_token),
):
    """Get variables available to a specific node from upstream nodes."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    from app.modules.automation.services.node_schema_service import get_available_variables as _get_vars

    return _get_vars(workflow, node_id)


@router.get("/workflows/endpoint-schema", tags=["Workflows"])
async def get_endpoint_schema(
    method: str = Query(..., description="HTTP method"),
    path: str = Query(..., description="API path template"),
    _current_user: User = Depends(get_current_user_from_token),
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
    current_user: User = Depends(get_current_user_from_token),
):
    """Simulate a workflow execution with optional dry-run mode."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

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

    # Execute in simulation mode
    from app.services.mist_service_factory import create_mist_service
    from app.modules.automation.services.executor_service import WorkflowExecutor

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

    # Return simulation results
    return {
        "execution_id": str(execution.id),
        "status": execution.status.value,
        "duration_ms": execution.duration_ms,
        "node_results": {
            nid: {
                "node_id": r.node_id,
                "node_name": r.node_name,
                "node_type": r.node_type,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "error": r.error,
                "output_data": r.output_data,
            }
            for nid, r in execution.node_results.items()
        },
        "node_snapshots": [
            {
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
            for s in execution.node_snapshots
        ],
        "variables": execution.variables,
        "logs": execution.logs,
    }


@router.get("/workflows/{workflow_id}/sample-payloads", tags=["Workflows"])
async def get_sample_payloads(
    workflow_id: str,
    limit: int = Query(10, ge=1, le=50),
    _current_user: User = Depends(get_current_user_from_token),
):
    """Get recent webhook events matching the workflow's trigger type for simulation."""
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workflow ID format") from exc

    if not workflow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    # Find the trigger node
    trigger_node = workflow.get_trigger_node()
    if not trigger_node:
        return {"payloads": []}

    webhook_type = trigger_node.config.get("webhook_topic") or trigger_node.config.get("webhook_type", "")
    if not webhook_type:
        return {"payloads": []}

    from app.modules.automation.models.webhook import WebhookEvent

    events = (
        await WebhookEvent.find(WebhookEvent.webhook_type == webhook_type)
        .sort("-received_at")
        .limit(limit)
        .to_list()
    )

    return {
        "payloads": [
            {
                "event_id": str(e.id),
                "timestamp": e.received_at,
                "topic": e.webhook_topic,
                "webhook_type": e.webhook_type,
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

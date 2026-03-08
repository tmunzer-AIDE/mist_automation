"""
Workflow automation API endpoints.
"""

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user_from_token
from app.modules.automation.models.execution import ExecutionStatus, WorkflowExecution
from app.models.user import User
from app.modules.automation.models.workflow import Workflow, WorkflowStatus, SharingPermission
from app.modules.automation.schemas.workflow import WorkflowCreate, WorkflowListResponse, WorkflowResponse, WorkflowUpdate

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
        trigger=wf.trigger.dict() if hasattr(wf.trigger, 'dict') else wf.trigger,
        filters=[f.dict() if hasattr(f, 'dict') else f for f in wf.filters],
        secondary_filters=[sf.dict() if hasattr(sf, 'dict') else sf for sf in wf.secondary_filters],
        actions=[a.dict() if hasattr(a, 'dict') else a for a in wf.actions],
        execution_count=wf.execution_count,
        success_count=wf.success_count,
        failure_count=wf.failure_count,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


@router.get("/workflows", response_model=WorkflowListResponse, tags=["Workflows"])
async def list_workflows(
    skip: int = Query(0, ge=0, description="Number of workflows to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of workflows to return"),
    status_filter: str | None = Query(None, description="Filter by status"),
    current_user: User = Depends(get_current_user_from_token)
):
    """
    List all workflows accessible to the current user.
    """
    # Build query - users see their own workflows or shared ones
    query = {"$or": [
        {"created_by": current_user.id},
        {"sharing": {"$in": [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]}}
    ]}
    
    if status_filter:
        query["status"] = status_filter
    
    # Get total count
    total = await Workflow.find(query).count()
    
    # Get workflows with pagination
    workflows = await Workflow.find(query).skip(skip).limit(limit).to_list()
    
    return WorkflowListResponse(
        workflows=[_workflow_to_response(wf) for wf in workflows],
        total=total
    )


@router.post("/workflows", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED, tags=["Workflows"])
async def create_workflow(
    workflow_data: WorkflowCreate,
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Create a new workflow.
    """
    # Create workflow
    workflow = Workflow(
        name=workflow_data.name,
        description=workflow_data.description,
        created_by=current_user.id,
        status=WorkflowStatus.DRAFT,
        timeout_seconds=workflow_data.timeout_seconds,
        trigger=workflow_data.trigger,
        filters=workflow_data.filters,
        secondary_filters=workflow_data.secondary_filters,
        actions=workflow_data.actions
    )
    await workflow.insert()
    
    logger.info("workflow_created", workflow_id=str(workflow.id), user_id=str(current_user.id))
    
    return _workflow_to_response(workflow)


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse, tags=["Workflows"])
async def get_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Get workflow details by ID.
    """
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workflow ID format"
        ) from exc
    
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    
    # Check access
    if not workflow.can_be_accessed_by(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    return _workflow_to_response(workflow)


@router.put("/workflows/{workflow_id}", response_model=WorkflowResponse, tags=["Workflows"])
async def update_workflow(
    workflow_id: str,
    workflow_data: WorkflowUpdate,
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Update workflow details.
    """
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workflow ID format"
        ) from exc
    
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    
    # Check ownership
    if str(workflow.created_by) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workflow owner can update it"
        )
    
    # Update fields
    if workflow_data.name is not None:
        workflow.name = workflow_data.name
    if workflow_data.description is not None:
        workflow.description = workflow_data.description
    if workflow_data.status is not None:
        workflow.status = WorkflowStatus(workflow_data.status)
    if workflow_data.timeout_seconds is not None:
        workflow.timeout_seconds = workflow_data.timeout_seconds
    if workflow_data.trigger is not None:
        workflow.trigger = workflow_data.trigger
    if workflow_data.filters is not None:
        workflow.filters = workflow_data.filters
    if workflow_data.secondary_filters is not None:
        workflow.secondary_filters = workflow_data.secondary_filters
    if workflow_data.actions is not None:
        workflow.actions = workflow_data.actions
    
    workflow.update_timestamp()
    await workflow.save()
    
    logger.info("workflow_updated", workflow_id=str(workflow.id), user_id=str(current_user.id))
    
    return _workflow_to_response(workflow)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Workflows"])
async def delete_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Delete a workflow.
    """
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workflow ID format"
        ) from exc
    
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    
    # Check ownership
    if str(workflow.created_by) != str(current_user.id) and not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workflow owner or admin can delete it"
        )
    
    await workflow.delete()
    logger.info("workflow_deleted", workflow_id=str(workflow.id), user_id=str(current_user.id))
    
    return None


@router.post("/workflows/{workflow_id}/execute", tags=["Workflows"])
async def execute_workflow(
    workflow_id: str,
    current_user: User = Depends(get_current_user_from_token)
):
    """
    Manually execute a workflow.
    """
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workflow ID format"
        ) from exc
    
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    
    # Check if workflow is enabled
    if workflow.status != WorkflowStatus.ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow must be enabled to execute"
        )
    
    # Create execution record
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        status=ExecutionStatus.PENDING,
        trigger_type="manual",
        triggered_by=current_user.id
    )
    await execution.insert()
    
    logger.info("workflow_execution_triggered", workflow_id=str(workflow.id), execution_id=str(execution.id), user_id=str(current_user.id))
    
    # In a real implementation, this would queue the workflow for execution
    # For now, return the execution ID
    return {
        "execution_id": str(execution.id),
        "status": "queued",
        "message": "Workflow execution has been queued"
    }


@router.get("/workflows/{workflow_id}/executions", tags=["Workflows"])
async def list_workflow_executions(
    workflow_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    _current_user: User = Depends(get_current_user_from_token)
):
    """
    List execution history for a workflow.
    """
    try:
        workflow = await Workflow.get(PydanticObjectId(workflow_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid workflow ID format"
        ) from exc
    
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )
    
    # Get executions
    total = await WorkflowExecution.find(WorkflowExecution.workflow_id == workflow.id).count()
    executions = await WorkflowExecution.find(
        WorkflowExecution.workflow_id == workflow.id
    ).sort("-started_at").skip(skip).limit(limit).to_list()
    
    return {
        "executions": [
            {
                "id": str(ex.id),
                "workflow_id": str(ex.workflow_id),
                "workflow_name": ex.workflow_name,
                "status": ex.status.value,
                "trigger_type": ex.trigger_type,
                "started_at": ex.started_at,
                "completed_at": ex.completed_at,
                "duration_ms": ex.duration_ms
            }
            for ex in executions
        ],
        "total": total
    }

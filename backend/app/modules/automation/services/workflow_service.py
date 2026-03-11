"""
Workflow service for CRUD operations and workflow management — graph model.
"""

from datetime import datetime, timezone
from typing import Optional

import structlog
from beanie import PydanticObjectId
from pymongo import DESCENDING

from app.modules.automation.models.workflow import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
    SharingPermission,
)
from app.models.user import User
from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationError

logger = structlog.get_logger(__name__)


class WorkflowService:
    """Service for workflow CRUD and management operations — graph model."""

    @staticmethod
    async def create_workflow(
        name: str,
        created_by: PydanticObjectId,
        nodes: list[WorkflowNode],
        edges: list[WorkflowEdge] | None = None,
        description: Optional[str] = None,
        timeout_seconds: int = 300,
        status: WorkflowStatus = WorkflowStatus.DRAFT,
        sharing: SharingPermission = SharingPermission.PRIVATE,
        viewport: dict | None = None,
        # Legacy compat: accept trigger+actions but they are now stored in nodes
        trigger=None,
        actions=None,
    ) -> Workflow:
        """Create a new graph-based workflow."""
        from app.modules.automation.services.graph_validator import validate_graph

        validate_graph(nodes, edges or [])

        workflow = Workflow(
            name=name,
            description=description,
            created_by=created_by,
            status=status,
            sharing=sharing,
            timeout_seconds=timeout_seconds,
            nodes=nodes,
            edges=edges or [],
            viewport=viewport,
        )

        await workflow.insert()
        logger.info("workflow_created", workflow_id=str(workflow.id), name=name, created_by=str(created_by))
        return workflow

    @staticmethod
    async def get_workflow(workflow_id: PydanticObjectId, user: User) -> Workflow:
        """Get a workflow by ID with permission check."""
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        if not WorkflowService._has_read_permission(workflow, user):
            raise PermissionDeniedError("You don't have permission to access this workflow")

        return workflow

    @staticmethod
    async def list_workflows(
        user: User,
        status: Optional[WorkflowStatus] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Workflow], int]:
        """List workflows accessible to the user."""
        query = {}

        if status:
            query["status"] = status

        if not user.is_admin():
            query["$or"] = [
                {"created_by": user.id},
                {"sharing": {"$in": [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]}},
            ]

        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
            ]

        workflows_query = Workflow.find(query).sort([("created_at", DESCENDING)])
        total = await workflows_query.count()
        workflows = await workflows_query.skip(skip).limit(limit).to_list()

        logger.debug("workflows_listed", count=len(workflows), total=total, user_id=str(user.id))
        return workflows, total

    @staticmethod
    async def update_workflow(
        workflow_id: PydanticObjectId,
        user: User,
        name: Optional[str] = None,
        description: Optional[str] = None,
        nodes: Optional[list[WorkflowNode]] = None,
        edges: Optional[list[WorkflowEdge]] = None,
        timeout_seconds: Optional[int] = None,
        sharing: Optional[SharingPermission] = None,
        viewport: dict | None = None,
    ) -> Workflow:
        """Update a workflow."""
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        if not WorkflowService._has_write_permission(workflow, user):
            raise PermissionDeniedError("You don't have permission to modify this workflow")

        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        if nodes is not None:
            from app.modules.automation.services.graph_validator import validate_graph

            validate_graph(nodes, edges if edges is not None else workflow.edges)
            workflow.nodes = nodes
            if edges is not None:
                workflow.edges = edges
        elif edges is not None:
            from app.modules.automation.services.graph_validator import validate_graph

            validate_graph(workflow.nodes, edges)
            workflow.edges = edges
        if timeout_seconds is not None:
            workflow.timeout_seconds = timeout_seconds
        if sharing is not None:
            workflow.sharing = sharing
        if viewport is not None:
            workflow.viewport = viewport

        workflow.updated_at = datetime.now(timezone.utc)
        await workflow.save()

        logger.info("workflow_updated", workflow_id=str(workflow_id), user_id=str(user.id))
        return workflow

    @staticmethod
    async def delete_workflow(workflow_id: PydanticObjectId, user: User) -> None:
        """Delete a workflow."""
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        if workflow.created_by != user.id and not user.is_admin():
            raise PermissionDeniedError("Only the workflow owner or admin can delete workflows")

        await workflow.delete()
        logger.info("workflow_deleted", workflow_id=str(workflow_id), user_id=str(user.id))

    @staticmethod
    async def update_workflow_status(
        workflow_id: PydanticObjectId,
        status: WorkflowStatus,
        user: User,
    ) -> Workflow:
        """Update workflow status (enable/disable/draft)."""
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        if not WorkflowService._has_write_permission(workflow, user):
            raise PermissionDeniedError("You don't have permission to modify this workflow")

        workflow.status = status
        workflow.updated_at = datetime.now(timezone.utc)
        await workflow.save()

        logger.info("workflow_status_updated", workflow_id=str(workflow_id), status=status, user_id=str(user.id))
        return workflow

    @staticmethod
    async def bulk_update_status(
        workflow_ids: list[PydanticObjectId],
        status: WorkflowStatus,
        user: User,
    ) -> int:
        """Bulk update workflow statuses."""
        updated_count = 0
        for workflow_id in workflow_ids:
            try:
                await WorkflowService.update_workflow_status(workflow_id, status, user)
                updated_count += 1
            except (NotFoundError, PermissionDeniedError) as e:
                logger.warning("bulk_update_failed_for_workflow", workflow_id=str(workflow_id), error=str(e))
                continue
        logger.info("bulk_status_update_completed", updated_count=updated_count, total=len(workflow_ids), user_id=str(user.id))
        return updated_count

    @staticmethod
    async def bulk_delete(workflow_ids: list[PydanticObjectId], user: User) -> int:
        """Bulk delete workflows."""
        deleted_count = 0
        for workflow_id in workflow_ids:
            try:
                await WorkflowService.delete_workflow(workflow_id, user)
                deleted_count += 1
            except (NotFoundError, PermissionDeniedError) as e:
                logger.warning("bulk_delete_failed_for_workflow", workflow_id=str(workflow_id), error=str(e))
                continue
        logger.info("bulk_delete_completed", deleted_count=deleted_count, total=len(workflow_ids), user_id=str(user.id))
        return deleted_count

    @staticmethod
    async def export_workflow(workflow_id: PydanticObjectId, user: User) -> dict:
        """Export workflow configuration as JSON."""
        workflow = await WorkflowService.get_workflow(workflow_id, user)
        export_data = workflow.model_dump(
            exclude={"id", "created_by", "created_at", "updated_at"},
            mode="json",
        )
        logger.info("workflow_exported", workflow_id=str(workflow_id), user_id=str(user.id))
        return export_data

    @staticmethod
    async def import_workflow(
        config: dict,
        user: User,
        name: Optional[str] = None,
    ) -> Workflow:
        """Import workflow from configuration dict."""
        if name:
            config["name"] = name
        config["created_by"] = user.id

        try:
            workflow = Workflow(**config)
            await workflow.insert()
            logger.info("workflow_imported", workflow_id=str(workflow.id), user_id=str(user.id))
            return workflow
        except Exception as e:
            logger.error("workflow_import_failed", error=str(e))
            raise ValidationError(f"Invalid workflow configuration: {e}")

    # ===== Permission Helpers =====

    @staticmethod
    def _has_read_permission(workflow: Workflow, user: User) -> bool:
        if user.is_admin():
            return True
        if workflow.created_by == user.id:
            return True
        if workflow.sharing in [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]:
            return True
        return False

    @staticmethod
    def _has_write_permission(workflow: Workflow, user: User) -> bool:
        if user.is_admin():
            return True
        if workflow.created_by == user.id:
            return True
        if workflow.sharing == SharingPermission.READ_WRITE:
            return True
        return False

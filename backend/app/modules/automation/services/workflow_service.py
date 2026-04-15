"""Compatibility workflow service for unit tests and legacy imports."""

from __future__ import annotations

from beanie import PydanticObjectId

from app.core.exceptions import ValidationError
from app.modules.automation.models.workflow import SharingPermission, Workflow, WorkflowStatus
from app.modules.automation.services.graph_validator import validate_graph


class WorkflowService:
    """Thin service wrapper around Workflow CRUD operations."""

    @staticmethod
    async def create_workflow(
        *,
        name: str,
        created_by: PydanticObjectId,
        nodes: list,
        edges: list,
    ) -> Workflow:
        """Create a standard workflow after validating graph structure."""
        try:
            validate_graph(nodes, edges, workflow_type="standard")
        except Exception as exc:
            raise ValidationError(str(exc)) from exc

        workflow = Workflow(
            name=name,
            created_by=created_by,
            status=WorkflowStatus.DRAFT,
            sharing=SharingPermission.PRIVATE,
            timeout_seconds=300,
            nodes=nodes,
            edges=edges,
        )
        await workflow.insert()
        return workflow

    @staticmethod
    async def list_workflows(user, *, skip: int = 0, limit: int = 100) -> tuple[list[Workflow], int]:
        """List workflows visible to the user with pagination metadata."""
        query = {
            "$or": [
                {"created_by": user.id},
                {"sharing": {"$in": [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]}},
            ]
        }

        total = await Workflow.find(query).count()
        workflows = await Workflow.find(query).sort("-created_at").skip(skip).limit(limit).to_list()
        return workflows, total

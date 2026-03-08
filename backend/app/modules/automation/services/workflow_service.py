"""
Workflow service for CRUD operations and workflow management.
"""

from datetime import datetime, timezone
from typing import Optional
import structlog
from beanie import PydanticObjectId
from pymongo import DESCENDING

from app.modules.automation.models.workflow import (
    Workflow,
    WorkflowStatus,
    SharingPermission,
    WorkflowTrigger,
    WorkflowFilter,
    WorkflowAction,
)
from app.models.user import User
from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationError

logger = structlog.get_logger(__name__)


class WorkflowService:
    """Service for workflow CRUD and management operations."""

    @staticmethod
    async def create_workflow(
        name: str,
        trigger: WorkflowTrigger,
        created_by: PydanticObjectId,
        description: Optional[str] = None,
        filters: Optional[list[WorkflowFilter]] = None,
        actions: Optional[list[WorkflowAction]] = None,
        timeout_seconds: int = 300,
        status: WorkflowStatus = WorkflowStatus.DRAFT,
        sharing: SharingPermission = SharingPermission.PRIVATE,
    ) -> Workflow:
        """
        Create a new workflow.

        Args:
            name: Workflow name
            trigger: Trigger configuration
            created_by: User ID who created the workflow
            description: Optional description
            filters: List of filters
            actions: List of actions
            timeout_seconds: Execution timeout
            status: Initial status
            sharing: Sharing permission

        Returns:
            Created workflow

        Raises:
            ValidationError: If workflow configuration is invalid
        """
        # Validate workflow configuration
        WorkflowService._validate_workflow_config(trigger, filters or [], actions or [])

        # Create workflow
        workflow = Workflow(
            name=name,
            description=description,
            created_by=created_by,
            status=status,
            sharing=sharing,
            timeout_seconds=timeout_seconds,
            trigger=trigger,
            filters=filters or [],
            secondary_filters=[],
            actions=actions or [],
        )

        await workflow.insert()
        logger.info(
            "workflow_created",
            workflow_id=str(workflow.id),
            name=name,
            created_by=str(created_by),
        )

        return workflow

    @staticmethod
    async def get_workflow(workflow_id: PydanticObjectId, user: User) -> Workflow:
        """
        Get a workflow by ID with permission check.

        Args:
            workflow_id: Workflow ID
            user: Current user

        Returns:
            Workflow object

        Raises:
            NotFoundError: If workflow not found
            PermissionDeniedError: If user doesn't have access
        """
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        # Check permissions
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
        """
        List workflows accessible to the user.

        Args:
            user: Current user
            status: Optional status filter
            search: Optional search term
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            tuple: (workflows, total_count)
        """
        # Build query
        query = {}

        # Filter by status
        if status:
            query["status"] = status

        # Filter by permissions (own workflows or shared workflows)
        if not user.is_admin():
            query["$or"] = [
                {"created_by": user.id},
                {"sharing": {"$in": [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]}},
            ]

        # Search by name or description
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
            ]

        # Get workflows
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
        trigger: Optional[WorkflowTrigger] = None,
        filters: Optional[list[WorkflowFilter]] = None,
        actions: Optional[list[WorkflowAction]] = None,
        timeout_seconds: Optional[int] = None,
        sharing: Optional[SharingPermission] = None,
    ) -> Workflow:
        """
        Update a workflow.

        Args:
            workflow_id: Workflow ID
            user: Current user
            name: New name
            description: New description
            trigger: New trigger configuration
            filters: New filters
            actions: New actions
            timeout_seconds: New timeout
            sharing: New sharing permission

        Returns:
            Updated workflow

        Raises:
            NotFoundError: If workflow not found
            PermissionDeniedError: If user doesn't have write permission
            ValidationError: If configuration is invalid
        """
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        # Check write permission
        if not WorkflowService._has_write_permission(workflow, user):
            raise PermissionDeniedError("You don't have permission to modify this workflow")

        # Update fields
        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        if trigger is not None:
            workflow.trigger = trigger
        if filters is not None:
            workflow.filters = filters
        if actions is not None:
            workflow.actions = actions
        if timeout_seconds is not None:
            workflow.timeout_seconds = timeout_seconds
        if sharing is not None:
            workflow.sharing = sharing

        # Validate configuration
        WorkflowService._validate_workflow_config(
            workflow.trigger,
            workflow.filters,
            workflow.actions,
        )

        workflow.updated_at = datetime.now(timezone.utc)
        await workflow.save()

        logger.info("workflow_updated", workflow_id=str(workflow_id), user_id=str(user.id))
        return workflow

    @staticmethod
    async def delete_workflow(workflow_id: PydanticObjectId, user: User) -> None:
        """
        Delete a workflow.

        Args:
            workflow_id: Workflow ID
            user: Current user

        Raises:
            NotFoundError: If workflow not found
            PermissionDeniedError: If user doesn't have permission
        """
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        # Only owner or admin can delete
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
        """
        Update workflow status (enable/disable/draft).

        Args:
            workflow_id: Workflow ID
            status: New status
            user: Current user

        Returns:
            Updated workflow

        Raises:
            NotFoundError: If workflow not found
            PermissionDeniedError: If user doesn't have permission
        """
        workflow = await Workflow.get(workflow_id)
        if not workflow:
            raise NotFoundError(f"Workflow {workflow_id} not found")

        # Check write permission
        if not WorkflowService._has_write_permission(workflow, user):
            raise PermissionDeniedError("You don't have permission to modify this workflow")

        workflow.status = status
        workflow.updated_at = datetime.now(timezone.utc)
        await workflow.save()

        logger.info(
            "workflow_status_updated",
            workflow_id=str(workflow_id),
            status=status,
            user_id=str(user.id),
        )
        return workflow

    @staticmethod
    async def bulk_update_status(
        workflow_ids: list[PydanticObjectId],
        status: WorkflowStatus,
        user: User,
    ) -> int:
        """
        Bulk update workflow statuses.

        Args:
            workflow_ids: List of workflow IDs
            status: New status
            user: Current user

        Returns:
            Number of workflows updated
        """
        updated_count = 0

        for workflow_id in workflow_ids:
            try:
                await WorkflowService.update_workflow_status(workflow_id, status, user)
                updated_count += 1
            except (NotFoundError, PermissionDeniedError) as e:
                logger.warning(
                    "bulk_update_failed_for_workflow",
                    workflow_id=str(workflow_id),
                    error=str(e),
                )
                continue

        logger.info(
            "bulk_status_update_completed",
            updated_count=updated_count,
            total=len(workflow_ids),
            user_id=str(user.id),
        )
        return updated_count

    @staticmethod
    async def bulk_delete(workflow_ids: list[PydanticObjectId], user: User) -> int:
        """
        Bulk delete workflows.

        Args:
            workflow_ids: List of workflow IDs
            user: Current user

        Returns:
            Number of workflows deleted
        """
        deleted_count = 0

        for workflow_id in workflow_ids:
            try:
                await WorkflowService.delete_workflow(workflow_id, user)
                deleted_count += 1
            except (NotFoundError, PermissionDeniedError) as e:
                logger.warning(
                    "bulk_delete_failed_for_workflow",
                    workflow_id=str(workflow_id),
                    error=str(e),
                )
                continue

        logger.info(
            "bulk_delete_completed",
            deleted_count=deleted_count,
            total=len(workflow_ids),
            user_id=str(user.id),
        )
        return deleted_count

    @staticmethod
    async def export_workflow(workflow_id: PydanticObjectId, user: User) -> dict:
        """
        Export workflow configuration as JSON.

        Args:
            workflow_id: Workflow ID
            user: Current user

        Returns:
            Workflow configuration dict

        Raises:
            NotFoundError: If workflow not found
            PermissionDeniedError: If user doesn't have access
        """
        workflow = await WorkflowService.get_workflow(workflow_id, user)

        # Export workflow (exclude internal fields)
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
        """
        Import workflow from configuration dict.

        Args:
            config: Workflow configuration
            user: Current user
            name: Optional name override

        Returns:
            Imported workflow

        Raises:
            ValidationError: If configuration is invalid
        """
        # Override name if provided
        if name:
            config["name"] = name

        # Set creator
        config["created_by"] = user.id

        # Create workflow from config
        try:
            workflow = Workflow(**config)
            await workflow.insert()

            logger.info("workflow_imported", workflow_id=str(workflow.id), user_id=str(user.id))
            return workflow

        except Exception as e:
            logger.error("workflow_import_failed", error=str(e))
            raise ValidationError(f"Invalid workflow configuration: {str(e)}")

    # ===== Permission Helpers =====

    @staticmethod
    def _has_read_permission(workflow: Workflow, user: User) -> bool:
        """Check if user has read permission for workflow."""
        if user.is_admin():
            return True
        if workflow.created_by == user.id:
            return True
        if workflow.sharing in [SharingPermission.READ_ONLY, SharingPermission.READ_WRITE]:
            return True
        return False

    @staticmethod
    def _has_write_permission(workflow: Workflow, user: User) -> bool:
        """Check if user has write permission for workflow."""
        if user.is_admin():
            return True
        if workflow.created_by == user.id:
            return True
        if workflow.sharing == SharingPermission.READ_WRITE:
            return True
        return False

    # ===== Validation Helpers =====

    @staticmethod
    def _validate_workflow_config(
        trigger: WorkflowTrigger,
        filters: list[WorkflowFilter],
        actions: list[WorkflowAction],
    ) -> None:
        """
        Validate workflow configuration.

        Raises:
            ValidationError: If configuration is invalid
        """
        # Validate trigger
        if trigger.type.value == "webhook":
            if not trigger.webhook_type:
                raise ValidationError("Webhook trigger requires webhook_type")
        elif trigger.type.value == "cron":
            if not trigger.cron_expression:
                raise ValidationError("Cron trigger requires cron_expression")
            from apscheduler.triggers.cron import CronTrigger
            try:
                CronTrigger.from_crontab(trigger.cron_expression)
            except ValueError as e:
                raise ValidationError(f"Invalid cron expression: {e}")

        # Validate that at least one action exists
        if not actions:
            raise ValidationError("Workflow must have at least one action")

        # Validate actions
        for i, action in enumerate(actions):
            if action.type.value.startswith("mist_api"):
                if not action.api_endpoint:
                    raise ValidationError(f"Action {i}: API endpoint required for {action.type}")

            elif action.type.value == "webhook":
                if not action.webhook_url:
                    raise ValidationError(f"Action {i}: Webhook URL required")

            elif action.type.value in ["slack", "servicenow", "pagerduty"]:
                if not action.notification_template:
                    raise ValidationError(f"Action {i}: Notification template required")

            elif action.type.value == "delay":
                if not action.delay_seconds or action.delay_seconds <= 0:
                    raise ValidationError(f"Action {i}: Valid delay_seconds required")

            elif action.type.value == "condition":
                if not action.condition:
                    raise ValidationError(f"Action {i}: Condition expression required")
                if not action.then_actions:
                    raise ValidationError(f"Action {i}: then_actions required for condition")

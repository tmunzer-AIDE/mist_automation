"""
APScheduler setup for cron-based workflow scheduling.
"""

from datetime import datetime, timezone
from typing import Optional
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from app.models.workflow import Workflow, WorkflowStatus, TriggerType
from app.config import settings

logger = structlog.get_logger(__name__)


class WorkflowScheduler:
    """Manages APScheduler for cron-based workflows."""

    def __init__(self):
        """Initialize the scheduler."""
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._initialized = False

    def _create_scheduler(self) -> AsyncIOScheduler:
        """Create and configure APScheduler instance."""
        jobstores = {
            'default': MemoryJobStore()
        }
        
        executors = {
            'default': AsyncIOExecutor()
        }
        
        job_defaults = {
            'coalesce': True,  # Combine missed runs into one
            'max_instances': 1,  # Only one instance per workflow
            'misfire_grace_time': 300  # 5 minutes grace period
        }

        scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )

        return scheduler

    async def start(self):
        """
        Start the scheduler and load all cron-based workflows.
        
        Called during application startup.
        """
        if self._initialized:
            logger.warning("scheduler_already_initialized")
            return

        self.scheduler = self._create_scheduler()
        
        # Load all enabled cron workflows
        await self._load_cron_workflows()
        
        # Start the scheduler
        self.scheduler.start()
        self._initialized = True
        
        logger.info(
            "scheduler_started",
            job_count=len(self.scheduler.get_jobs())
        )

    async def stop(self):
        """
        Stop the scheduler gracefully.
        
        Called during application shutdown.
        """
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("scheduler_stopped")
            self._initialized = False

    async def _load_cron_workflows(self):
        """Load all enabled cron workflows from database."""
        try:
            # Find all enabled workflows with cron triggers
            workflows = await Workflow.find(
                Workflow.status == WorkflowStatus.ENABLED,
                Workflow.trigger.type == TriggerType.CRON
            ).to_list()

            for workflow in workflows:
                await self.add_workflow(workflow)

            logger.info(
                "cron_workflows_loaded",
                count=len(workflows)
            )

        except Exception as e:
            logger.error(
                "failed_to_load_cron_workflows",
                error=str(e)
            )

    async def add_workflow(self, workflow: Workflow):
        """
        Add or update a cron workflow in the scheduler.

        Args:
            workflow: Workflow to schedule

        Raises:
            ValueError: If workflow trigger is not cron type or invalid cron expression
        """
        if not workflow.trigger or workflow.trigger.type != TriggerType.CRON:
            raise ValueError(f"Workflow {workflow.id} is not a cron workflow")

        if not workflow.trigger.cron_expression:
            raise ValueError(f"Workflow {workflow.id} missing cron expression")

        if workflow.status != WorkflowStatus.ENABLED:
            logger.debug(
                "skipping_disabled_workflow",
                workflow_id=str(workflow.id)
            )
            return

        job_id = f"workflow_{workflow.id}"

        try:
            # Remove existing job if present
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            # Parse cron expression
            cron_expr = workflow.trigger.cron_expression
            # APScheduler expects: minute hour day month day_of_week
            parts = cron_expr.split()
            if len(parts) != 5:
                raise ValueError(f"Invalid cron expression: {cron_expr}")

            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone='UTC'
            )

            # Add job to scheduler
            self.scheduler.add_job(
                self._execute_workflow,
                trigger=trigger,
                id=job_id,
                name=workflow.name,
                kwargs={
                    'workflow_id': str(workflow.id),
                    'workflow_name': workflow.name
                },
                replace_existing=True
            )

            # Get next run time
            job = self.scheduler.get_job(job_id)
            next_run = job.next_run_time if job else None

            logger.info(
                "workflow_scheduled",
                workflow_id=str(workflow.id),
                workflow_name=workflow.name,
                cron_expression=cron_expr,
                next_run=next_run.isoformat() if next_run else None
            )

        except Exception as e:
            logger.error(
                "failed_to_schedule_workflow",
                workflow_id=str(workflow.id),
                workflow_name=workflow.name,
                error=str(e)
            )
            raise

    async def remove_workflow(self, workflow_id: str):
        """
        Remove a workflow from the scheduler.

        Args:
            workflow_id: Workflow ID to remove
        """
        job_id = f"workflow_{workflow_id}"
        
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(
                "workflow_unscheduled",
                workflow_id=workflow_id
            )
        else:
            logger.debug(
                "workflow_not_in_scheduler",
                workflow_id=workflow_id
            )

    async def _execute_workflow(self, workflow_id: str, workflow_name: str):
        """
        Execute a scheduled workflow.

        Args:
            workflow_id: Workflow ID to execute
            workflow_name: Workflow name (for logging)
        """
        from app.workers.cron_worker import execute_cron_workflow

        logger.info(
            "cron_workflow_triggered",
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            triggered_at=datetime.now(timezone.utc).isoformat()
        )

        try:
            # Execute the workflow asynchronously
            await execute_cron_workflow(workflow_id)

        except Exception as e:
            logger.error(
                "cron_workflow_execution_failed",
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                error=str(e)
            )

    def get_scheduled_workflows(self) -> list[dict]:
        """
        Get list of all scheduled workflows.

        Returns:
            List of workflow schedule info
        """
        if not self.scheduler:
            return []

        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                'job_id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger),
            })

        return jobs


# Global scheduler instance
_scheduler_instance: Optional[WorkflowScheduler] = None


def get_scheduler() -> WorkflowScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = WorkflowScheduler()
    return _scheduler_instance


async def start_scheduler():
    """Start the global scheduler instance."""
    scheduler = get_scheduler()
    await scheduler.start()


async def stop_scheduler():
    """Stop the global scheduler instance."""
    scheduler = get_scheduler()
    await scheduler.stop()

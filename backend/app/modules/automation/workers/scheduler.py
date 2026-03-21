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

from app.modules.automation.models.workflow import Workflow, WorkflowStatus

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

        # Load scheduled backup job
        await self._load_backup_schedule()

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
            workflows = await Workflow.find(
                Workflow.status == WorkflowStatus.ENABLED,
                {"nodes": {"$elemMatch": {"type": "trigger", "config.trigger_type": "cron"}}},
            ).to_list()

            for workflow in workflows:
                await self.add_workflow(workflow)

            logger.info("cron_workflows_loaded", count=len(workflows))

        except Exception as e:
            logger.error("failed_to_load_cron_workflows", error=str(e))

    async def add_workflow(self, workflow: Workflow):
        """Add or update a cron workflow in the scheduler."""
        trigger_node = workflow.get_trigger_node()
        if not trigger_node or trigger_node.config.get("trigger_type") != "cron":
            raise ValueError(f"Workflow {workflow.id} is not a cron workflow")

        cron_expr = trigger_node.config.get("cron_expression")
        if not cron_expr:
            raise ValueError(f"Workflow {workflow.id} missing cron expression")

        if workflow.status != WorkflowStatus.ENABLED:
            logger.debug("skipping_disabled_workflow", workflow_id=str(workflow.id))
            return

        job_id = f"workflow_{workflow.id}"

        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
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
        from app.modules.automation.workers.cron_worker import execute_cron_workflow

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

    async def _load_backup_schedule(self):
        """Load backup schedule from system config."""
        try:
            from app.models.system import SystemConfig
            config = await SystemConfig.get_config()
            if config and config.backup_enabled and config.backup_full_schedule_cron:
                await self.schedule_backup(config.backup_full_schedule_cron)
            else:
                logger.info("backup_schedule_disabled_or_not_configured")
        except Exception as e:
            logger.error("failed_to_load_backup_schedule", error=str(e))

    async def schedule_backup(self, cron_expression: str):
        """Add or update the scheduled backup job."""
        if not self.scheduler:
            logger.warning("scheduler_not_initialized")
            return

        job_id = "scheduled_full_backup"

        # Remove existing job if present
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        parts = cron_expression.split()
        if len(parts) != 5:
            logger.error("invalid_backup_cron_expression", cron=cron_expression)
            return

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone='UTC',
        )

        self.scheduler.add_job(
            self._execute_backup,
            trigger=trigger,
            id=job_id,
            name="Scheduled Full Backup",
            replace_existing=True,
        )

        job = self.scheduler.get_job(job_id)
        next_run = job.next_run_time if job else None

        logger.info(
            "backup_scheduled",
            cron_expression=cron_expression,
            next_run=next_run.isoformat() if next_run else None,
        )

    async def unschedule_backup(self):
        """Remove the scheduled backup job."""
        if not self.scheduler:
            return
        job_id = "scheduled_full_backup"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info("backup_unscheduled")

    async def _execute_backup(self):
        """Execute a scheduled full backup."""
        from app.models.system import SystemConfig
        from app.core.security import decrypt_sensitive_data
        from app.modules.backup.models import BackupJob, BackupType, BackupStatus
        from app.modules.backup.workers import perform_backup

        logger.info("scheduled_backup_triggered")

        try:
            config = await SystemConfig.get_config()
            if not config or not config.backup_enabled:
                logger.info("scheduled_backup_skipped_disabled")
                return

            org_id = config.mist_org_id

            # Create a backup job record
            job = BackupJob(
                backup_type=BackupType.SCHEDULED,
                org_id=org_id or "",
                status=BackupStatus.PENDING,
            )
            await job.insert()

            # Run the backup
            await perform_backup(
                backup_id=str(job.id),
                backup_type="scheduled",
                org_id=org_id,
            )

        except Exception as e:
            logger.error("scheduled_backup_failed", error=str(e))

    def schedule_aggregation_fire(self, window_id: str, fire_at: datetime) -> None:
        """Schedule a one-shot job to fire an aggregation window."""
        from apscheduler.triggers.date import DateTrigger

        job_id = f"aggregation_{window_id}"
        self.scheduler.add_job(
            _fire_aggregation_job,
            trigger=DateTrigger(run_date=fire_at),
            id=job_id,
            replace_existing=True,
            coalesce=True,
            kwargs={"window_id": window_id},
        )
        logger.info("aggregation_fire_scheduled", window_id=window_id, fire_at=fire_at.isoformat())

    def cancel_aggregation_fire(self, window_id: str) -> None:
        """Cancel a scheduled aggregation fire job."""
        job_id = f"aggregation_{window_id}"
        try:
            self.scheduler.remove_job(job_id)
            logger.info("aggregation_fire_cancelled", window_id=window_id)
        except Exception:
            pass  # Job may not exist

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


def _fire_aggregation_job(window_id: str) -> None:
    """APScheduler callback — fires an aggregation window."""
    from app.core.tasks import create_background_task
    from app.modules.automation.workers.aggregation_worker import fire_aggregation_window

    create_background_task(fire_aggregation_window(window_id), name=f"fire-aggregation-{window_id}")


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

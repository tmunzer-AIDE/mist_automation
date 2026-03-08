"""
Backup worker - handles scheduled and on-demand backup operations using Celery.
"""

from datetime import datetime, timezone
from typing import Any, Optional
import structlog
from celery import Celery
from beanie import PydanticObjectId

from app.models.backup import BackupJob, BackupStatus, BackupType
from app.services.backup_service import BackupService
from app.services.git_service import GitService
from app.services.mist_service import MistService
from app.config import settings

logger = structlog.get_logger(__name__)

# Initialize Celery (reuse same app as webhook worker)
from app.workers.webhook_worker import celery_app


@celery_app.task(name='perform_backup', bind=True, max_retries=2)
def perform_backup_task(
    self,
    backup_id: str,
    backup_type: str = "scheduled",
    org_id: Optional[str] = None,
    site_id: Optional[str] = None
):
    """
    Celery task to perform a configuration backup.

    Args:
        backup_id: BackupJob ID
        backup_type: Type of backup (scheduled, manual, pre_change)
        org_id: Organization ID
        site_id: Site ID (optional, for site-specific backups)

    Returns:
        dict: Backup result
    """
    import asyncio
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        perform_backup(backup_id, backup_type, org_id, site_id)
    )


async def perform_backup(
    backup_id: str,
    backup_type: str = "scheduled",
    org_id: Optional[str] = None,
    site_id: Optional[str] = None
) -> dict[str, Any]:
    """
    Perform a configuration backup operation.

    Args:
        backup_id: BackupJob ID
        backup_type: Type of backup
        org_id: Organization ID
        site_id: Site ID (optional)

    Returns:
        dict: Backup result with statistics
    """
    start_time = datetime.now(timezone.utc)

    try:
        # Get backup job record
        backup_job = await BackupJob.get(PydanticObjectId(backup_id))
        if not backup_job:
            raise ValueError(f"Backup job {backup_id} not found")

        # Update status
        backup_job.status = BackupStatus.RUNNING
        backup_job.started_at = start_time
        await backup_job.save()

        logger.info(
            "backup_started",
            backup_id=backup_id,
            backup_type=backup_type,
            org_id=org_id,
            site_id=site_id
        )

        # Initialize services
        mist_service = MistService(
            api_token=settings.mist_api_token,
            org_id=org_id or settings.mist_org_id
        )
        backup_service = BackupService(mist_service=mist_service)

        # Perform backup
        result = await backup_service.perform_full_backup()

        # Update backup job with results
        backup_job.status = BackupStatus.COMPLETED
        backup_job.completed_at = datetime.now(timezone.utc)
        backup_job.object_count = result.get("total_objects", 0)
        backup_job.size_bytes = result.get("total_size_bytes", 0)
        
        # Calculate duration
        if backup_job.started_at and backup_job.completed_at:
            delta = backup_job.completed_at - backup_job.started_at
            duration_ms = int(delta.total_seconds() * 1000)
        else:
            duration_ms = 0

        await backup_job.save()

        # Git integration (if enabled)
        if settings.backup_git_enabled and settings.backup_git_repo_url:
            try:
                git_service = GitService(
                    repo_url=settings.backup_git_repo_url,
                    branch=settings.backup_git_branch,
                    author_name=settings.backup_git_author_name,
                    author_email=settings.backup_git_author_email
                )

                commit_sha = await git_service.commit_backup(
                    backup_id=backup_id,
                    message=f"Automated backup - {backup_type}",
                    objects_count=backup_job.object_count
                )

                logger.info(
                    "backup_committed_to_git",
                    backup_id=backup_id,
                    commit_sha=commit_sha
                )

            except Exception as e:
                logger.warning(
                    "git_commit_failed",
                    backup_id=backup_id,
                    error=str(e)
                )
                # Don't fail the backup if Git fails

        logger.info(
            "backup_completed",
            backup_id=backup_id,
            duration_ms=duration_ms,
            object_count=backup_job.object_count,
            size_bytes=backup_job.size_bytes
        )

        return {
            "backup_id": backup_id,
            "status": "completed",
            "duration_ms": duration_ms,
            "object_count": backup_job.object_count,
            "size_bytes": backup_job.size_bytes,
            "details": result
        }

    except Exception as e:
        logger.error(
            "backup_failed",
            backup_id=backup_id,
            error=str(e)
        )

        # Mark backup as failed
        if backup_job:
            backup_job.status = BackupStatus.FAILED
            backup_job.completed_at = datetime.now(timezone.utc)
            backup_job.error = str(e)
            await backup_job.save()

        raise


async def perform_restore(backup_id: str, dry_run: bool = False):
    """Restore from a backup job."""
    backup = await BackupJob.get(backup_id)
    if not backup:
        logger.error(f"BackupJob {backup_id} not found")
        return
    try:
        backup.status = BackupStatus.IN_PROGRESS
        await backup.save()
        from app.services.restore_service import RestoreService
        restore_service = RestoreService()
        await restore_service.restore_backup(backup, dry_run=dry_run)
        backup.status = BackupStatus.COMPLETED
        await backup.save()
    except Exception as e:
        logger.error(f"Restore failed for {backup_id}: {e}")
        backup.status = BackupStatus.FAILED
        backup.error = str(e)
        await backup.save()


@celery_app.task(name='cleanup_old_backups')
def cleanup_old_backups_task():
    """
    Celery task to clean up old backups based on retention policy.
    
    Returns:
        dict: Cleanup result
    """
    import asyncio
    
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(cleanup_old_backups())


async def cleanup_old_backups() -> dict[str, Any]:
    """
    Clean up old backups based on retention policy.

    Returns:
        dict: Cleanup statistics
    """
    try:
        logger.info("backup_cleanup_started")

        # Calculate cutoff date
        cutoff_date = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cutoff_date = cutoff_date.replace(day=cutoff_date.day - settings.backup_retention_days)

        # Find old backups
        old_backups = await BackupJob.find(
            BackupJob.created_at < cutoff_date,
            BackupJob.status.in_([BackupStatus.COMPLETED, BackupStatus.FAILED])
        ).to_list()

        deleted_count = 0
        for backup in old_backups:
            await backup.delete()
            deleted_count += 1

        logger.info(
            "backup_cleanup_completed",
            deleted_count=deleted_count,
            cutoff_date=cutoff_date.isoformat()
        )

        return {
            "status": "completed",
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "retention_days": settings.backup_retention_days
        }

    except Exception as e:
        logger.error("backup_cleanup_failed", error=str(e))
        raise


def queue_backup(
    backup_id: str,
    backup_type: str = "scheduled",
    org_id: Optional[str] = None,
    site_id: Optional[str] = None
) -> str:
    """
    Queue a backup operation for asynchronous processing.

    Args:
        backup_id: BackupJob ID
        backup_type: Type of backup
        org_id: Organization ID
        site_id: Site ID (optional)

    Returns:
        str: Celery task ID
    """
    task = perform_backup_task.delay(backup_id, backup_type, org_id, site_id)
    
    logger.info(
        "backup_queued",
        backup_id=backup_id,
        backup_type=backup_type,
        task_id=task.id
    )
    
    return task.id


def schedule_periodic_backups():
    """
    Set up periodic backup tasks using Celery Beat.
    
    This should be configured in Celery Beat schedule.
    """
    # Configure in celerybeat-schedule.py or via celery_app.conf.beat_schedule
    celery_app.conf.beat_schedule = {
        'daily-full-backup': {
            'task': 'perform_backup',
            'schedule': settings.backup_full_schedule_cron,
            'args': (None, 'scheduled', settings.mist_org_id, None)
        },
        'weekly-cleanup': {
            'task': 'cleanup_old_backups',
            'schedule': '0 3 * * 0',  # Weekly on Sunday at 3 AM
        },
    }

    logger.info(
        "periodic_backups_scheduled",
        full_backup_schedule=settings.backup_full_schedule_cron
    )

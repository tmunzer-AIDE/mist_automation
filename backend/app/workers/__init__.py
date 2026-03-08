"""
Background workers for async task processing.

This module contains:
- webhook_worker: Process incoming webhooks asynchronously
- cron_worker: Execute scheduled workflows
- backup_worker: Handle backup operations
- scheduler: APScheduler integration for cron triggers
"""

from app.workers.scheduler import (
    WorkflowScheduler,
    get_scheduler,
    start_scheduler,
    stop_scheduler
)
from app.workers.webhook_worker import (
    celery_app,
    queue_webhook_processing,
    process_webhook
)
from app.workers.cron_worker import (
    execute_cron_workflow,
    get_cron_workflow_status
)
from app.workers.backup_worker import (
    queue_backup,
    cleanup_old_backups,
    schedule_periodic_backups
)

__all__ = [
    # Scheduler
    'WorkflowScheduler',
    'get_scheduler',
    'start_scheduler',
    'stop_scheduler',
    
    # Webhook worker
    'celery_app',
    'queue_webhook_processing',
    'process_webhook',
    
    # Cron worker
    'execute_cron_workflow',
    'get_cron_workflow_status',
    
    # Backup worker
    'queue_backup',
    'cleanup_old_backups',
    'schedule_periodic_backups',
]

"""
Service layer exports for easy importing.

Imports are lazy to avoid circular dependency issues.
"""

__all__ = [
    "AuthService",
    "MistService",
    "get_mist_service",
    "WorkflowService",
    "WorkflowExecutor",
    "BackupService",
    "RestoreService",
    "GitService",
    "NotificationService",
]


def __getattr__(name: str):
    if name == "AuthService":
        from app.services.auth_service import AuthService
        return AuthService
    if name in ("MistService", "get_mist_service"):
        from app.services.mist_service import MistService, get_mist_service
        return MistService if name == "MistService" else get_mist_service
    if name == "WorkflowService":
        from app.modules.automation.services.workflow_service import WorkflowService
        return WorkflowService
    if name == "WorkflowExecutor":
        from app.modules.automation.services.executor_service import WorkflowExecutor
        return WorkflowExecutor
    if name == "BackupService":
        from app.modules.backup.services.backup_service import BackupService
        return BackupService
    if name == "RestoreService":
        from app.modules.backup.services.restore_service import RestoreService
        return RestoreService
    if name == "GitService":
        from app.modules.backup.services.git_service import GitService
        return GitService
    if name == "NotificationService":
        from app.services.notification_service import NotificationService
        return NotificationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""
Custom exceptions for the application.
"""

from typing import Any, Optional


class MistAutomationException(Exception):
    """Base exception for all application exceptions."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: Optional[dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


# Authentication & Authorization Exceptions
class AuthenticationException(MistAutomationException):
    """Raised when authentication fails."""
    
    def __init__(self, message: str = "Authentication failed", details: Optional[dict] = None):
        super().__init__(message, status_code=401, details=details)


class InvalidCredentialsException(AuthenticationException):
    """Raised when login credentials are invalid."""
    
    def __init__(self, message: str = "Invalid email or password"):
        super().__init__(message)


class TokenExpiredException(AuthenticationException):
    """Raised when JWT token has expired."""
    
    def __init__(self, message: str = "Token has expired"):
        super().__init__(message)


class InvalidTokenException(AuthenticationException):
    """Raised when JWT token is invalid."""
    
    def __init__(self, message: str = "Invalid token"):
        super().__init__(message)


class AuthorizationException(MistAutomationException):
    """Raised when user lacks required permissions."""
    
    def __init__(self, message: str = "Insufficient permissions", details: Optional[dict] = None):
        super().__init__(message, status_code=403, details=details)


class TwoFactorRequiredException(AuthenticationException):
    """Raised when 2FA code is required."""
    
    def __init__(self, message: str = "Two-factor authentication code required"):
        super().__init__(message)


class Invalid2FACodeException(AuthenticationException):
    """Raised when 2FA code is invalid."""
    
    def __init__(self, message: str = "Invalid two-factor authentication code"):
        super().__init__(message)


# User Management Exceptions
class UserNotFoundException(MistAutomationException):
    """Raised when user is not found."""
    
    def __init__(self, message: str = "User not found", user_id: Optional[str] = None):
        details = {"user_id": user_id} if user_id else None
        super().__init__(message, status_code=404, details=details)


class UserAlreadyExistsException(MistAutomationException):
    """Raised when trying to create a user that already exists."""
    
    def __init__(self, message: str = "User already exists", email: Optional[str] = None):
        details = {"email": email} if email else None
        super().__init__(message, status_code=409, details=details)


class WeakPasswordException(MistAutomationException):
    """Raised when password doesn't meet security requirements."""
    
    def __init__(self, message: str):
        super().__init__(message, status_code=400)


# Workflow Exceptions
class WorkflowNotFoundException(MistAutomationException):
    """Raised when workflow is not found."""
    
    def __init__(self, message: str = "Workflow not found", workflow_id: Optional[str] = None):
        details = {"workflow_id": workflow_id} if workflow_id else None
        super().__init__(message, status_code=404, details=details)


class WorkflowValidationException(MistAutomationException):
    """Raised when workflow configuration is invalid."""
    
    def __init__(self, message: str, validation_errors: Optional[dict] = None):
        super().__init__(message, status_code=400, details=validation_errors)


class WorkflowExecutionException(MistAutomationException):
    """Raised when workflow execution fails."""
    
    def __init__(
        self,
        message: str,
        workflow_id: Optional[str] = None,
        execution_id: Optional[str] = None
    ):
        details = {}
        if workflow_id:
            details["workflow_id"] = workflow_id
        if execution_id:
            details["execution_id"] = execution_id
        super().__init__(message, status_code=500, details=details)


class WorkflowTimeoutException(WorkflowExecutionException):
    """Raised when workflow execution times out."""

    def __init__(self, timeout_seconds: int):
        super().__init__(f"Workflow execution timed out after {timeout_seconds} seconds")


class WorkflowPausedException(MistAutomationException):
    """Workflow paused at a wait_for_callback node."""

    def __init__(self, node_id: str, message: str = ""):
        self.node_id = node_id
        super().__init__(
            message=message or f"Workflow paused at node '{node_id}', awaiting callback",
            status_code=202,
            details={"node_id": node_id},
        )


# Webhook Exceptions
class WebhookValidationException(MistAutomationException):
    """Raised when webhook validation fails."""
    
    def __init__(self, message: str = "Webhook validation failed"):
        super().__init__(message, status_code=400)


class InvalidWebhookSignatureException(WebhookValidationException):
    """Raised when webhook signature is invalid."""
    
    def __init__(self, message: str = "Invalid webhook signature"):
        super().__init__(message)


# Mist API Exceptions
class MistAPIException(MistAutomationException):
    """Raised when Mist API call fails."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        api_status_code: Optional[int] = None
    ):
        details = {"api_status_code": api_status_code} if api_status_code else None
        super().__init__(message, status_code=status_code, details=details)


class MistAPINotConfiguredException(MistAutomationException):
    """Raised when Mist API is not configured."""
    
    def __init__(self, message: str = "Mist API not configured"):
        super().__init__(message, status_code=503)


# Backup Exceptions
class BackupNotFoundException(MistAutomationException):
    """Raised when backup object is not found."""
    
    def __init__(self, message: str = "Backup not found", backup_id: Optional[str] = None):
        details = {"backup_id": backup_id} if backup_id else None
        super().__init__(message, status_code=404, details=details)


class RestoreException(MistAutomationException):
    """Raised when restore operation fails."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, status_code=500, details=details)


class GitOperationException(MistAutomationException):
    """Raised when Git operation fails."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, status_code=500, details=details)


# Validation Exceptions
class ValidationException(MistAutomationException):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else None
        super().__init__(message, status_code=400, details=details)


class ConfigurationException(MistAutomationException):
    """Raised when configuration is invalid or missing."""
    
    def __init__(self, message: str = "Configuration error"):
        super().__init__(message, status_code=500)


class DataNotFoundException(MistAutomationException):
    """Raised when requested data is not found."""
    
    def __init__(self, message: str = "Not found", resource_type: Optional[str] = None):
        details = {"resource_type": resource_type} if resource_type else None
        super().__init__(message, status_code=404, details=details)


class PermissionDeniedException(MistAutomationException):
    """Raised when user doesn't have permission for an action."""
    
    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, status_code=403)


class NotificationException(MistAutomationException):
    """Raised when notification delivery fails."""
    
    def __init__(self, message: str, platform: Optional[str] = None):
        details = {"platform": platform} if platform else None
        super().__init__(message, status_code=500, details=details)


class BackupException(MistAutomationException):
    """Raised when backup operation fails."""
    
    def __init__(self, message: str):
        super().__init__(message, status_code=500)


# ===== Aliases for shorter/alternative names =====

# For auth_service
AuthenticationError = AuthenticationException
InvalidCredentialsError = InvalidCredentialsException
UserNotFoundError = UserNotFoundException
UserInactiveError = UserNotFoundException
TOTPRequiredError = TwoFactorRequiredException
InvalidTOTPError = Invalid2FACodeException

# For workflow_service
NotFoundError = DataNotFoundException
PermissionDeniedError = PermissionDeniedException
ValidationError = ValidationException

# For executor_service
WorkflowExecutionError = WorkflowExecutionException
WorkflowTimeoutError = WorkflowTimeoutException
WorkflowPausedError = WorkflowPausedException

# For mist_service
MistAPIError = MistAPIException
ConfigurationError = ConfigurationException

# For backup/restore services
BackupError = BackupException
RestoreError = RestoreException

# For git_service
GitError = GitOperationException

# For notification_service
NotificationError = NotificationException

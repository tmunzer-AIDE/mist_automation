"""
Dependency injection utilities for FastAPI.
Provides reusable dependencies for authentication, authorization, and common operations.
"""

from typing import Optional
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId
import structlog

from app.core.security import decode_token
from app.core.exceptions import (
    AuthenticationException,
    AuthorizationException,
    InvalidTokenException,
    TokenExpiredException,
)
from app.models.user import User
from app.models.session import UserSession

logger = structlog.get_logger(__name__)

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)


async def get_current_user_from_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """
    Extract and validate JWT token, return current user.
    
    Args:
        request: FastAPI request object
        credentials: HTTP Authorization header credentials
    
    Returns:
        User: Authenticated user
    
    Raises:
        AuthenticationException: If token is missing or invalid
    """
    if not credentials:
        logger.warning("authentication_failed", reason="no_token_provided")
        raise AuthenticationException("Authentication required")
    
    token = credentials.credentials
    
    # Decode and validate token
    payload = decode_token(token)
    if not payload:
        logger.warning("authentication_failed", reason="invalid_token")
        raise InvalidTokenException()
    
    # Extract user ID and token JTI
    user_id_str = payload.get("sub")
    token_jti = payload.get("jti")
    
    if not user_id_str or not token_jti:
        logger.warning("authentication_failed", reason="missing_claims")
        raise InvalidTokenException("Token missing required claims")
    
    # Check if session exists and is valid
    session = await UserSession.find_one(UserSession.token_jti == token_jti)
    if not session:
        logger.warning("authentication_failed", reason="session_not_found", token_jti=token_jti)
        raise InvalidTokenException("Session not found or has been revoked")
    
    if session.is_expired():
        logger.warning("authentication_failed", reason="session_expired", token_jti=token_jti)
        raise TokenExpiredException()
    
    # Get user
    try:
        user_id = ObjectId(user_id_str)
    except Exception as exc:
        logger.warning("authentication_failed", reason="invalid_user_id", user_id=user_id_str)
        raise InvalidTokenException("Invalid user ID") from exc
    
    user = await User.get(user_id)
    if not user:
        logger.warning("authentication_failed", reason="user_not_found", user_id=user_id_str)
        raise AuthenticationException("User not found")
    
    if not user.is_active:
        logger.warning("authentication_failed", reason="user_inactive", user_id=user_id_str)
        raise AuthenticationException("User account is inactive")
    
    # Update session activity
    session.update_activity()
    await session.save()
    
    # Attach session to request state for later use
    request.state.session = session
    request.state.token_jti = token_jti
    
    logger.info(
        "user_authenticated",
        user_id=str(user.id),
        user_email=user.email,
        request_id=getattr(request.state, "request_id", None),
    )
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user_from_token),
) -> User:
    """
    Get current active user (alias for get_current_user_from_token).
    
    Args:
        current_user: User from token validation
    
    Returns:
        User: Active authenticated user
    """
    return current_user


async def require_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Require user to have admin role.
    
    Args:
        current_user: Authenticated user
    
    Returns:
        User: User with admin role
    
    Raises:
        AuthorizationException: If user is not an admin
    """
    if not current_user.is_admin():
        logger.warning(
            "authorization_failed",
            user_id=str(current_user.id),
            user_email=current_user.email,
            required_role="admin",
        )
        raise AuthorizationException("Admin privileges required")
    
    return current_user


async def require_automation_role(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Require user to have automation or admin role.
    
    Args:
        current_user: Authenticated user
    
    Returns:
        User: User with automation or admin role
    
    Raises:
        AuthorizationException: If user lacks required role
    """
    if not current_user.can_manage_workflows():
        logger.warning(
            "authorization_failed",
            user_id=str(current_user.id),
            user_email=current_user.email,
            required_role="automation",
        )
        raise AuthorizationException("Automation role required")
    
    return current_user


async def require_backup_role(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Require user to have backup or admin role.

    Args:
        current_user: Authenticated user

    Returns:
        User: User with backup or admin role

    Raises:
        AuthorizationException: If user lacks required role
    """
    if not current_user.can_manage_backups():
        logger.warning(
            "authorization_failed",
            user_id=str(current_user.id),
            user_email=current_user.email,
            required_role="backup",
        )
        raise AuthorizationException("Backup role required")

    return current_user


async def require_reports_role(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Require user to have reports or admin role.

    Args:
        current_user: Authenticated user

    Returns:
        User: User with reports or admin role

    Raises:
        AuthorizationException: If user lacks required role
    """
    if not current_user.can_manage_reports():
        logger.warning(
            "authorization_failed",
            user_id=str(current_user.id),
            user_email=current_user.email,
            required_role="reports",
        )
        raise AuthorizationException("Reports role required")

    return current_user


def get_client_info(request: Request) -> dict:
    """
    Extract client information from request.
    
    Args:
        request: FastAPI request object
    
    Returns:
        dict: Client information (IP, user agent, etc.)
    """
    return {
        "ip_address": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent"),
        "x_forwarded_for": request.headers.get("x-forwarded-for"),
        "x_real_ip": request.headers.get("x-real-ip"),
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[User]:
    """
    Get current user if authenticated, otherwise return None.
    Useful for endpoints that have different behavior for authenticated vs anonymous users.
    
    Args:
        credentials: HTTP Authorization header credentials
    
    Returns:
        Optional[User]: Authenticated user or None
    """
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = decode_token(token)
        
        if not payload:
            return None
        
        user_id_str = payload.get("sub")
        if not user_id_str:
            return None
        
        user_id = ObjectId(user_id_str)
        user = await User.get(user_id)
        
        if user and user.is_active:
            return user
        
        return None
    except Exception:
        return None

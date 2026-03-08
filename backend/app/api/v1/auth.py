"""
Authentication API endpoints.
"""

from datetime import timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import settings
from app.core.security import create_access_token, verify_password
from app.dependencies import get_current_user_from_token
from app.models.session import UserSession
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(request: Request, login_data: LoginRequest):
    """
    Login endpoint - authenticate user and return JWT token.
    """
    # Find user by email
    user = await User.find_one(User.email == login_data.email)
    if not user:
        logger.warning("login_failed", email=login_data.email, reason="user_not_found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Verify password
    if not verify_password(login_data.password, user.password_hash):
        logger.warning("login_failed", email=login_data.email, reason="invalid_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Check if user is active
    if not user.is_active:
        logger.warning("login_failed", email=login_data.email, reason="user_inactive")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )
    
    # Create JWT token
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "roles": user.roles,
    }
    
    expires_delta = timedelta(hours=settings.access_token_expire_hours)
    if login_data.remember_me:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)
    
    access_token, token_jti = create_access_token(data=token_data, expires_delta=expires_delta)
    
    # Create session record
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    
    session = UserSession.create_session(
        user_id=user.id,
        token_jti=token_jti,
        ip_address=ip_address,
        user_agent=user_agent,
        trusted_device=login_data.remember_me
    )
    await session.insert()
    
    # Update last login
    user.update_last_login()
    await user.save()
    
    logger.info("user_logged_in", user_id=str(user.id), email=user.email)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds())
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["Authentication"])
async def logout(request: Request, current_user: User = Depends(get_current_user_from_token)):
    """
    Logout endpoint - invalidate JWT token.
    """
    # Get token JTI from request state (set by dependency)
    token_jti = getattr(request.state, "token_jti", None)
    
    if token_jti:
        # Delete the session
        session = await UserSession.find_one(UserSession.token_jti == token_jti)
        if session:
            await session.delete()
            logger.info("user_logged_out", user_id=str(current_user.id), token_jti=token_jti)
    
    return None


@router.post("/auth/refresh", response_model=TokenResponse, tags=["Authentication"])
async def refresh_token(current_user: User = Depends(get_current_user_from_token)):
    """
    Refresh JWT token.
    """
    # Create new JWT token
    token_data = {
        "sub": str(current_user.id),
        "email": current_user.email,
        "roles": current_user.roles,
    }
    
    expires_delta = timedelta(hours=settings.access_token_expire_hours)
    access_token, token_jti = create_access_token(data=token_data, expires_delta=expires_delta)
    
    logger.info("token_refreshed", user_id=str(current_user.id))
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds())
    )


@router.get("/auth/me", response_model=UserResponse, tags=["Authentication"])
async def get_current_user(current_user: User = Depends(get_current_user_from_token)):
    """
    Get current authenticated user information.
    """
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        roles=current_user.roles,
        timezone=current_user.timezone,
        is_active=current_user.is_active,
        totp_enabled=current_user.totp_enabled,
        created_at=current_user.created_at,
        last_login=current_user.last_login
    )

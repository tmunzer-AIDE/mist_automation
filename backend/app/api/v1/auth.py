"""
Authentication API endpoints.
"""

import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.errors import DuplicateKeyError
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from app.config import settings
from app.core.redis_client import get_challenge_store
from app.core.security import (
    create_access_token,
    hash_password,
    validate_password_with_policy,
    verify_password,
)
from app.dependencies import get_current_user_from_token
from app.models.session import UserSession
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    OnboardRequest,
    PasskeyDeleteRequest,
    PasskeyListResponse,
    PasskeyLoginBeginResponse,
    PasskeyLoginCompleteRequest,
    PasskeyRegisterBeginResponse,
    PasskeyRegisterCompleteRequest,
    PasskeyResponse,
    SessionListResponse,
    SessionResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from app.services.passkey_service import PasskeyError, PasskeyService

router = APIRouter()
logger = structlog.get_logger(__name__)


def _user_to_response(user: User) -> UserResponse:
    """Build a UserResponse from a User document."""
    from app.schemas.user import user_to_response

    return user_to_response(user)


# ── In-memory rate limiter for login ──────────────────────────────────────────
_login_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 300  # 5 minutes
_RATE_LIMIT_MAX = 5  # max attempts per window


async def _get_passkey_service() -> PasskeyService:
    """Create a PasskeyService with the current configuration."""
    store = await get_challenge_store()
    return PasskeyService(
        challenge_store=store,
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        expected_origin=settings.webauthn_origin,
    )


def _check_login_rate_limit(key: str) -> None:
    """Raise 429 if the key has exceeded the login rate limit."""
    now = time.monotonic()
    # Prune old entries
    recent = [t for t in _login_attempts[key] if now - t < _RATE_LIMIT_WINDOW]
    if not recent:
        # Remove empty keys to prevent unbounded dict growth
        _login_attempts.pop(key, None)
    else:
        _login_attempts[key] = recent
    if len(recent) >= _RATE_LIMIT_MAX:
        logger.warning("login_rate_limited", key=key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )
    _login_attempts[key].append(now)

    # Probabilistic cleanup of stale entries to prevent memory leak
    if random.random() < 0.01:
        stale_keys = [k for k, v in _login_attempts.items() if now - v[-1] > _RATE_LIMIT_WINDOW]
        for k in stale_keys:
            del _login_attempts[k]


@router.post("/auth/login", response_model=TokenResponse, tags=["Authentication"])
async def login(request: Request, login_data: LoginRequest):
    """
    Login endpoint - authenticate user and return JWT token.
    """
    # Rate limit by IP + email
    ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(f"{ip}:{login_data.email}")

    # Find user by email
    user = await User.find_one(User.email == login_data.email)
    if not user:
        logger.warning("login_failed", email=login_data.email, reason="user_not_found")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    # Verify password
    if not verify_password(login_data.password, user.password_hash):
        logger.warning("login_failed", email=login_data.email, reason="invalid_password")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    # Check if user is active
    if not user.is_active:
        logger.warning("login_failed", email=login_data.email, reason="user_inactive")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

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

    # Create session record first, then trim excess (insert-then-trim is race-safe)
    from app.models.system import SystemConfig

    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")

    session = UserSession.create_session(
        user_id=user.id,
        token_jti=token_jti,
        ip_address=ip_address,
        user_agent=user_agent,
        trusted_device=login_data.remember_me,
        expires_delta=expires_delta,
    )
    await session.insert()

    # Enforce max concurrent sessions by trimming oldest
    sys_config = await SystemConfig.get_config()
    max_sessions = sys_config.max_concurrent_sessions or 5
    excess = await UserSession.find(UserSession.user_id == user.id).sort("last_activity").to_list()
    if len(excess) > max_sessions:
        for old_session in excess[: len(excess) - max_sessions]:
            await old_session.delete()

    # Update last login
    user.update_last_login()
    await user.save()

    logger.info("user_logged_in", user_id=str(user.id), email=user.email)

    return TokenResponse(access_token=access_token, token_type="bearer", expires_in=int(expires_delta.total_seconds()))


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
async def refresh_token(request: Request, current_user: User = Depends(get_current_user_from_token)):
    """
    Refresh JWT token.
    Invalidates the old session and creates a new one.
    """
    # Delete old session
    old_jti = getattr(request.state, "token_jti", None)
    if old_jti:
        old_session = await UserSession.find_one(UserSession.token_jti == old_jti)
        if old_session:
            await old_session.delete()

    # Create new JWT token
    token_data = {
        "sub": str(current_user.id),
        "email": current_user.email,
        "roles": current_user.roles,
    }

    expires_delta = timedelta(hours=settings.access_token_expire_hours)
    access_token, token_jti = create_access_token(data=token_data, expires_delta=expires_delta)

    # Create new session
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    new_session = UserSession.create_session(
        user_id=current_user.id,
        token_jti=token_jti,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await new_session.insert()

    logger.info("token_refreshed", user_id=str(current_user.id))

    return TokenResponse(access_token=access_token, token_type="bearer", expires_in=int(expires_delta.total_seconds()))


@router.get("/auth/me", response_model=UserResponse, tags=["Authentication"])
async def get_current_user(current_user: User = Depends(get_current_user_from_token)):
    """
    Get current authenticated user information.
    """
    return _user_to_response(current_user)


@router.put("/auth/profile", response_model=UserResponse, tags=["Authentication"])
async def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Update current user's profile settings (e.g. timezone).
    """
    if data.first_name is not None:
        current_user.first_name = data.first_name
    if data.last_name is not None:
        current_user.last_name = data.last_name
    if data.timezone is not None:
        current_user.timezone = data.timezone
    current_user.update_timestamp()
    await current_user.save()

    logger.info("profile_updated", user_id=str(current_user.id))

    return _user_to_response(current_user)


@router.post("/auth/onboard", response_model=TokenResponse, tags=["Authentication"])
async def onboard(request: Request, data: OnboardRequest):
    """
    Onboarding endpoint - create the first admin user.
    Only works when no users exist in the system.
    """
    user_count = await User.find().count()
    if user_count > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="System is already initialized")

    is_valid, error_msg = await validate_password_with_policy(data.password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        roles=["admin", "automation", "backup", "post_deployment", "impact_analysis"],
    )
    try:
        await user.insert()
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System is already initialized",
        ) from exc

    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "roles": user.roles,
    }
    expires_delta = timedelta(hours=settings.access_token_expire_hours)
    access_token, token_jti = create_access_token(data=token_data, expires_delta=expires_delta)

    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    session = UserSession.create_session(
        user_id=user.id,
        token_jti=token_jti,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await session.insert()

    user.update_last_login()
    user.update_timestamp()
    await user.save()

    logger.info("system_onboarded", user_id=str(user.id), email=user.email)

    return TokenResponse(access_token=access_token, token_type="bearer", expires_in=int(expires_delta.total_seconds()))


@router.post("/auth/change-password", tags=["Authentication"])
async def change_password(
    request: Request,
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Change password for the current user.
    """
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    is_valid, error_msg = await validate_password_with_policy(data.new_password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    current_user.password_hash = hash_password(data.new_password)
    current_user.update_timestamp()
    await current_user.save()

    # Invalidate all other sessions (keep current)
    current_jti = getattr(request.state, "token_jti", None)
    if current_jti:
        await UserSession.find(
            UserSession.user_id == current_user.id,
            UserSession.token_jti != current_jti,
        ).delete()
    else:
        await UserSession.find(UserSession.user_id == current_user.id).delete()

    logger.info("password_changed", user_id=str(current_user.id))

    # Audit log
    from app.models.system import AuditLog

    await AuditLog.log_event(
        event_type="password_changed",
        event_category="auth",
        description="User changed their password",
        user_id=current_user.id,
        user_email=current_user.email,
    )

    return {"message": "Password changed successfully"}


@router.get("/auth/sessions", response_model=SessionListResponse, tags=["Authentication"])
async def get_sessions(
    request: Request,
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Get active sessions for the current user.
    """
    sessions = await UserSession.find(UserSession.user_id == current_user.id).sort("-last_activity").to_list()

    current_jti = getattr(request.state, "token_jti", None)

    session_list = [
        SessionResponse(
            id=str(s.id),
            user_id=str(s.user_id),
            device_info=s.device_info.model_dump(),
            trusted_device=s.trusted_device,
            created_at=s.created_at,
            last_activity=s.last_activity,
            expires_at=s.expires_at,
            is_current=(s.token_jti == current_jti),
        )
        for s in sessions
    ]

    return SessionListResponse(sessions=session_list, total=len(session_list))


@router.delete(
    "/auth/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Authentication"],
)
async def revoke_session(
    session_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_from_token),
):
    """
    Revoke a specific session. Cannot revoke the current session.
    """
    from bson import ObjectId

    try:
        sid = ObjectId(session_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session ID") from exc

    session = await UserSession.get(sid)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    current_jti = getattr(request.state, "token_jti", None)
    if session.token_jti == current_jti:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot revoke current session")

    await session.delete()
    logger.info("session_revoked", user_id=str(current_user.id), session_id=session_id)

    return None


# ── Passkey / WebAuthn ──────────────────────────────────────────────────────


@router.post(
    "/auth/passkey/register/begin",
    response_model=PasskeyRegisterBeginResponse,
    tags=["Authentication"],
)
async def passkey_register_begin(current_user: User = Depends(get_current_user_from_token)):
    """Begin passkey registration — returns challenge options."""
    service = await _get_passkey_service()
    try:
        session_id, options = await service.generate_registration_options(current_user)
    except PasskeyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    return PasskeyRegisterBeginResponse(session_id=session_id, options=options)


@router.post(
    "/auth/passkey/register/complete",
    response_model=PasskeyResponse,
    tags=["Authentication"],
)
async def passkey_register_complete(
    data: PasskeyRegisterCompleteRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Complete passkey registration — verify attestation and store credential."""
    service = await _get_passkey_service()
    try:
        credential = await service.verify_registration(
            user=current_user,
            session_id=data.session_id,
            credential_json=data.credential,
            name=data.name,
        )
    except PasskeyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None

    current_user.webauthn_credentials.append(credential)
    current_user.update_timestamp()
    await current_user.save()

    logger.info("passkey_registered", user_id=str(current_user.id), name=data.name)

    return PasskeyResponse(
        id=bytes_to_base64url(credential.credential_id),
        name=credential.name,
        created_at=credential.created_at,
        last_used_at=credential.last_used_at,
        transports=credential.transports,
    )


@router.post(
    "/auth/passkey/login/begin",
    response_model=PasskeyLoginBeginResponse,
    tags=["Authentication"],
)
async def passkey_login_begin(request: Request):
    """Begin passkey authentication — returns challenge options (no auth required)."""
    ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(f"{ip}:passkey")

    service = await _get_passkey_service()
    session_id, options = await service.generate_authentication_options()
    return PasskeyLoginBeginResponse(session_id=session_id, options=options)


@router.post(
    "/auth/passkey/login/complete",
    response_model=TokenResponse,
    tags=["Authentication"],
)
async def passkey_login_complete(request: Request, data: PasskeyLoginCompleteRequest):
    """Complete passkey authentication — verify assertion and return JWT."""
    import json as json_mod

    ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(f"{ip}:passkey")

    # Extract credential_id from the assertion to find the user
    try:
        cred_data = json_mod.loads(data.credential)
        raw_id_b64 = cred_data.get("rawId") or cred_data.get("id")
        credential_id_bytes = base64url_to_bytes(raw_id_b64)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credential format") from exc

    # Find user by credential_id
    user = await User.find_one({"webauthn_credentials.credential_id": credential_id_bytes})
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid passkey")

    # Find the matching stored credential
    stored_cred = None
    for cred in user.webauthn_credentials:
        if cred.credential_id == credential_id_bytes:
            stored_cred = cred
            break

    if stored_cred is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid passkey")

    service = await _get_passkey_service()
    try:
        new_sign_count = await service.verify_authentication(
            session_id=data.session_id,
            credential_json=data.credential,
            credential_id_bytes=credential_id_bytes,
            stored_credential=stored_cred,
        )
    except PasskeyError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from None

    # Update credential state
    stored_cred.sign_count = new_sign_count
    stored_cred.last_used_at = datetime.now(timezone.utc)
    user.update_timestamp()
    await user.save()

    # Create JWT + session (same as password login)
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "roles": user.roles,
    }
    expires_delta = timedelta(hours=settings.access_token_expire_hours)
    access_token, token_jti = create_access_token(data=token_data, expires_delta=expires_delta)

    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    session = UserSession.create_session(
        user_id=user.id,
        token_jti=token_jti,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_delta=expires_delta,
    )
    await session.insert()

    from app.models.system import SystemConfig

    sys_config = await SystemConfig.get_config()
    max_sessions = sys_config.max_concurrent_sessions or 5
    excess = await UserSession.find(UserSession.user_id == user.id).sort("last_activity").to_list()
    if len(excess) > max_sessions:
        for old_session in excess[: len(excess) - max_sessions]:
            await old_session.delete()

    user.update_last_login()
    await user.save()

    logger.info("user_logged_in_passkey", user_id=str(user.id), email=user.email)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(expires_delta.total_seconds()),
    )


@router.get(
    "/auth/passkeys",
    response_model=PasskeyListResponse,
    tags=["Authentication"],
)
async def list_passkeys(current_user: User = Depends(get_current_user_from_token)):
    """List current user's registered passkeys."""
    passkeys = [
        PasskeyResponse(
            id=bytes_to_base64url(cred.credential_id),
            name=cred.name,
            created_at=cred.created_at,
            last_used_at=cred.last_used_at,
            transports=cred.transports,
        )
        for cred in current_user.webauthn_credentials
    ]
    return PasskeyListResponse(passkeys=passkeys, total=len(passkeys))


@router.post(
    "/auth/passkey/{credential_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Authentication"],
)
async def delete_passkey(
    credential_id: str,
    data: PasskeyDeleteRequest,
    current_user: User = Depends(get_current_user_from_token),
):
    """Delete a passkey. Requires password re-authentication."""
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password")

    try:
        cred_id_bytes = base64url_to_bytes(credential_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid credential ID") from exc

    original_count = len(current_user.webauthn_credentials)
    current_user.webauthn_credentials = [
        c for c in current_user.webauthn_credentials if c.credential_id != cred_id_bytes
    ]

    if len(current_user.webauthn_credentials) == original_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passkey not found")

    current_user.update_timestamp()
    await current_user.save()

    logger.info("passkey_deleted", user_id=str(current_user.id), credential_id=credential_id)
    return None

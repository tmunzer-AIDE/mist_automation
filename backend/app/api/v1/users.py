"""
User management API endpoints.
"""

from datetime import datetime, timezone

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pymongo.errors import DuplicateKeyError

from app.core.pat import generate_pat
from app.core.security import hash_password, validate_password_with_policy
from app.dependencies import get_current_user_from_token, require_admin
from app.models.personal_access_token import PersonalAccessToken
from app.models.system import AuditLog, SystemConfig
from app.models.user import User
from app.schemas.personal_access_token import (
    PATCreateRequest,
    PATCreateResponse,
    PATListResponse,
    PATResponse,
)
from app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate

router = APIRouter()
logger = structlog.get_logger(__name__)


def _pat_to_response(pat: PersonalAccessToken) -> PATResponse:
    return PATResponse(
        id=str(pat.id),
        name=pat.name,
        token_prefix=pat.token_prefix,
        scopes=pat.scopes,
        created_at=pat.created_at,
        expires_at=pat.expires_at,
        last_used_at=pat.last_used_at,
        revoked_at=pat.revoked_at,
    )


def _user_to_response(user: User) -> UserResponse:
    from app.schemas.user import user_to_response

    return user_to_response(user)


@router.get("/users", response_model=UserListResponse, tags=["Users"])
async def list_users(
    skip: int = Query(0, ge=0, description="Number of users to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of users to return"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    current_user: User = Depends(require_admin),
):
    """
    List all users (admin only).
    """
    # Build query
    query = {}
    if is_active is not None:
        query["is_active"] = is_active

    # Get total count
    total = await User.find(query).count()

    # Get users with pagination
    users = await User.find(query).skip(skip).limit(limit).to_list()

    return UserListResponse(users=[_user_to_response(user) for user in users], total=total)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED, tags=["Users"])
async def create_user(user_data: UserCreate, current_user: User = Depends(require_admin)):
    """
    Create a new user (admin only).
    """
    # Validate password strength
    is_valid, error_msg = await validate_password_with_policy(user_data.password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    # Check if user already exists
    existing_user = await User.find_one(User.email == user_data.email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this email already exists")

    # Hash password
    password_hash = hash_password(user_data.password)

    # Create user
    user = User(
        email=user_data.email,
        password_hash=password_hash,
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        roles=user_data.roles,
        timezone=user_data.timezone,
        is_active=True,
    )
    await user.insert()

    logger.info("user_created", user_id=str(user.id), email=user.email, created_by=str(current_user.id))

    return _user_to_response(user)


@router.get("/users/{user_id}", response_model=UserResponse, tags=["Users"])
async def get_user(user_id: str, current_user: User = Depends(require_admin)):
    """
    Get user details by ID.
    """
    try:
        user = await User.get(PydanticObjectId(user_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID format") from exc

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return _user_to_response(user)


@router.put("/users/{user_id}", response_model=UserResponse, tags=["Users"])
async def update_user(user_id: str, user_data: UserUpdate, current_user: User = Depends(require_admin)):
    """
    Update user details.
    """
    try:
        user = await User.get(PydanticObjectId(user_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID format") from exc

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Update fields
    if user_data.email is not None:
        # Check if email is already taken
        existing = await User.find_one(User.email == user_data.email, User.id != user.id)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
        user.email = user_data.email

    if user_data.first_name is not None:
        user.first_name = user_data.first_name
    if user_data.last_name is not None:
        user.last_name = user_data.last_name

    if user_data.roles is not None:
        user.roles = user_data.roles

    if user_data.timezone is not None:
        user.timezone = user_data.timezone

    if user_data.is_active is not None:
        if str(user.id) == str(current_user.id) and not user_data.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot disable your own account")
        user.is_active = user_data.is_active

    user.update_timestamp()
    await user.save()

    logger.info("user_updated", user_id=str(user.id), updated_by=str(current_user.id))

    return _user_to_response(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Users"])
async def delete_user(user_id: str, current_user: User = Depends(require_admin)):
    """
    Delete a user (admin only).
    """
    try:
        user = await User.get(PydanticObjectId(user_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user ID format") from exc

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Prevent self-deletion
    if str(user.id) == str(current_user.id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    await user.delete()
    logger.info("user_deleted", user_id=str(user.id), deleted_by=str(current_user.id))

    return None


# ---------------------------------------------------------------------------
# Personal Access Tokens (self-service) — used to authenticate external MCP
# clients. Every authenticated user can manage their own tokens.
# ---------------------------------------------------------------------------


@router.get("/users/me/tokens", response_model=PATListResponse, tags=["Personal Access Tokens"])
async def list_my_tokens(
    current_user: User = Depends(get_current_user_from_token),
):
    """List the caller's active (usable) personal access tokens."""
    config = await SystemConfig.get_config()
    tokens = (
        await PersonalAccessToken.find(
            PersonalAccessToken.user_id == current_user.id,
            PersonalAccessToken.revoked_at == None,  # noqa: E711 — Beanie requires `== None`
        )
        .sort("-created_at")
        .to_list()
    )
    active_tokens = [t for t in tokens if t.is_usable()]
    return PATListResponse(
        tokens=[_pat_to_response(t) for t in active_tokens],
        total=len(active_tokens),
        max_per_user=config.max_pats_per_user,
    )


@router.post(
    "/users/me/tokens",
    response_model=PATCreateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Personal Access Tokens"],
)
async def create_my_token(
    payload: PATCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user_from_token),
):
    """Create a new PAT. The plaintext token is returned exactly once."""
    config = await SystemConfig.get_config()

    existing_tokens = await PersonalAccessToken.find(
        PersonalAccessToken.user_id == current_user.id,
        PersonalAccessToken.revoked_at == None,  # noqa: E711
    ).to_list()
    active_count = sum(1 for token in existing_tokens if token.is_usable())
    if active_count >= config.max_pats_per_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Token limit reached ({config.max_pats_per_user}). Revoke an existing token first.",
        )

    if payload.expires_at is not None:
        expires = payload.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="expires_at must be in the future",
            )

    plaintext = ""
    pat: PersonalAccessToken | None = None
    for attempt in range(3):
        plaintext, token_hash, token_prefix = generate_pat()
        candidate = PersonalAccessToken(
            user_id=current_user.id,
            name=payload.name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            expires_at=payload.expires_at,
        )
        try:
            await candidate.insert()
            pat = candidate
            break
        except DuplicateKeyError:
            logger.warning(
                "pat_token_hash_collision",
                user_id=str(current_user.id),
                attempt=attempt + 1,
            )

    if pat is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unable to create token due to token collision. Please retry.",
        )

    await AuditLog.log_event(
        event_type="pat_created",
        event_category="auth",
        description=f"Created personal access token '{pat.name}'",
        user_id=current_user.id,
        user_email=current_user.email,
        source_ip=request.client.host if request.client else None,
        target_type="personal_access_token",
        target_id=str(pat.id),
        target_name=pat.name,
        details={"prefix": pat.token_prefix, "expires_at": pat.expires_at.isoformat() if pat.expires_at else None},
    )
    logger.info(
        "pat_created",
        user_id=str(current_user.id),
        pat_id=str(pat.id),
        prefix=pat.token_prefix,
    )

    base = _pat_to_response(pat)
    return PATCreateResponse(**base.model_dump(), token=plaintext)


@router.delete(
    "/users/me/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Personal Access Tokens"],
)
async def revoke_my_token(
    token_id: str,
    request: Request,
    current_user: User = Depends(get_current_user_from_token),
):
    """Revoke a PAT owned by the caller."""
    try:
        pat = await PersonalAccessToken.get(PydanticObjectId(token_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token ID format",
        ) from exc

    if not pat or pat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    if pat.revoked_at is not None:
        return None

    pat.revoked_at = datetime.now(timezone.utc)
    pat.update_timestamp()
    await pat.save()

    await AuditLog.log_event(
        event_type="pat_revoked",
        event_category="auth",
        description=f"Revoked personal access token '{pat.name}'",
        user_id=current_user.id,
        user_email=current_user.email,
        source_ip=request.client.host if request.client else None,
        target_type="personal_access_token",
        target_id=str(pat.id),
        target_name=pat.name,
    )
    logger.info("pat_revoked", user_id=str(current_user.id), pat_id=str(pat.id))
    return None

"""
User management API endpoints.
"""

import structlog
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import hash_password
from app.dependencies import get_current_user_from_token, require_admin
from app.models.user import User
from app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate

router = APIRouter()
logger = structlog.get_logger(__name__)


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        roles=user.roles,
        timezone=user.timezone,
        is_active=user.is_active,
        totp_enabled=user.totp_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login,
    )


@router.get("/users", response_model=UserListResponse, tags=["Users"])
async def list_users(
    skip: int = Query(0, ge=0, description="Number of users to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of users to return"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    current_user: User = Depends(require_admin)
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
    
    return UserListResponse(
        users=[_user_to_response(user) for user in users],
        total=total
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED, tags=["Users"])
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create a new user (admin only).
    """
    # Check if user already exists
    existing_user = await User.find_one(User.email == user_data.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )
    
    # Hash password
    password_hash = hash_password(user_data.password)
    
    # Create user
    user = User(
        email=user_data.email,
        password_hash=password_hash,
        roles=user_data.roles,
        timezone=user_data.timezone,
        is_active=True
    )
    await user.insert()
    
    logger.info("user_created", user_id=str(user.id), email=user.email, created_by=str(current_user.id))
    
    return _user_to_response(user)


@router.get("/users/{user_id}", response_model=UserResponse, tags=["Users"])
async def get_user(
    user_id: str,
    current_user: User = Depends(require_admin)
):
    """
    Get user details by ID.
    """
    try:
        user = await User.get(PydanticObjectId(user_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format"
        ) from exc
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return _user_to_response(user)


@router.put("/users/{user_id}", response_model=UserResponse, tags=["Users"])
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(require_admin)
):
    """
    Update user details.
    """
    try:
        user = await User.get(PydanticObjectId(user_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format"
        ) from exc
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update fields
    if user_data.email is not None:
        # Check if email is already taken
        existing = await User.find_one(User.email == user_data.email, User.id != user.id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use"
            )
        user.email = user_data.email
    
    if user_data.roles is not None:
        user.roles = user_data.roles
    
    if user_data.timezone is not None:
        user.timezone = user_data.timezone
    
    if user_data.is_active is not None:
        user.is_active = user_data.is_active
    
    user.update_timestamp()
    await user.save()
    
    logger.info("user_updated", user_id=str(user.id), updated_by=str(current_user.id))
    
    return _user_to_response(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Users"])
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_admin)
):
    """
    Delete a user (admin only).
    """
    try:
        user = await User.get(PydanticObjectId(user_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID format"
        ) from exc
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent self-deletion
    if str(user.id) == str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    await user.delete()
    logger.info("user_deleted", user_id=str(user.id), deleted_by=str(current_user.id))
    
    return None

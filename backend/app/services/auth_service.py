"""
Authentication service for user login, token management, and 2FA.
"""

from datetime import datetime, timezone
from typing import Optional
import pyotp
import qrcode
import io
import base64
import structlog

from beanie import PydanticObjectId

from app.models.user import User
from app.models.session import UserSession, DeviceInfo
from app.core.security import (
    hash_password,
    verify_password,
    validate_password_strength,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_backup_codes,
    hash_backup_code,
)
from app.core.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    UserNotFoundError,
    UserInactiveError,
    TOTPRequiredError,
    InvalidTOTPError,
)
from app.config import settings

logger = structlog.get_logger(__name__)


class AuthService:
    """Service for handling authentication and authorization."""

    @staticmethod
    async def authenticate_user(
        email: str,
        password: str,
        totp_code: Optional[str] = None,
        device_info: Optional[DeviceInfo] = None,
    ) -> tuple[User, str, str]:
        """
        Authenticate a user with email and password, optionally validating 2FA.

        Args:
            email: User email address
            password: Plain text password
            totp_code: Optional TOTP code for 2FA
            device_info: Optional device information for session tracking

        Returns:
            tuple: (user, access_token, refresh_token)

        Raises:
            InvalidCredentialsError: If credentials are invalid
            UserNotFoundError: If user doesn't exist
            UserInactiveError: If user account is inactive
            TOTPRequiredError: If 2FA is enabled but code not provided
            InvalidTOTPError: If TOTP code is invalid
        """
        # Find user by email
        user = await User.find_one(User.email == email)
        if not user:
            logger.warning("login_failed_user_not_found", email=email)
            raise InvalidCredentialsError("Invalid email or password")

        # Verify password
        if not verify_password(password, user.password_hash):
            logger.warning("login_failed_invalid_password", user_id=str(user.id), email=email)
            raise InvalidCredentialsError("Invalid email or password")

        # Check if user is active
        if not user.is_active:
            logger.warning("login_failed_user_inactive", user_id=str(user.id), email=email)
            raise UserInactiveError("User account is inactive")

        # Handle 2FA if enabled
        if user.totp_enabled:
            if not totp_code:
                logger.info("login_requires_2fa", user_id=str(user.id))
                raise TOTPRequiredError("2FA code required")

            # Validate TOTP code
            if not await AuthService.verify_totp(user, totp_code):
                logger.warning("login_failed_invalid_totp", user_id=str(user.id))
                raise InvalidTOTPError("Invalid 2FA code")

        # Update last login timestamp
        user.last_login = datetime.now(timezone.utc)
        await user.save()

        # Generate tokens
        access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
        refresh_token = create_refresh_token(data={"sub": str(user.id)})

        # Create session record if device info provided
        if device_info:
            token_payload = decode_token(access_token)
            if token_payload:
                await UserSession.create_session(
                    user_id=user.id,
                    token_jti=token_payload["jti"],
                    device_info=device_info,
                )

        logger.info("user_login_success", user_id=str(user.id), email=user.email)
        return user, access_token, refresh_token

    @staticmethod
    async def create_user(
        email: str,
        password: str,
        roles: Optional[list[str]] = None,
        timezone: str = "UTC",
    ) -> User:
        """
        Create a new user account.

        Args:
            email: User email address
            password: Plain text password
            roles: List of roles to assign
            timezone: User timezone

        Returns:
            Created user object

        Raises:
            ValueError: If password doesn't meet requirements or user exists
        """
        # Validate password strength
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            logger.warning("user_creation_failed_weak_password", email=email, error=error_msg)
            raise ValueError(error_msg)

        # Check if user already exists
        existing_user = await User.find_one(User.email == email)
        if existing_user:
            logger.warning("user_creation_failed_duplicate_email", email=email)
            raise ValueError(f"User with email {email} already exists")

        # Create user
        user = User(
            email=email,
            password_hash=hash_password(password),
            roles=roles or [],
            timezone=timezone,
            is_active=True,
        )
        await user.insert()

        logger.info("user_created", user_id=str(user.id), email=email, roles=roles)
        return user

    @staticmethod
    async def change_password(
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """
        Change user password after verifying current password.

        Args:
            user: User object
            current_password: Current password for verification
            new_password: New password to set

        Raises:
            InvalidCredentialsError: If current password is incorrect
            ValueError: If new password doesn't meet requirements
        """
        # Verify current password
        if not verify_password(current_password, user.password_hash):
            logger.warning("password_change_failed_invalid_current", user_id=str(user.id))
            raise InvalidCredentialsError("Current password is incorrect")

        # Validate new password strength
        is_valid, error_msg = validate_password_strength(new_password)
        if not is_valid:
            logger.warning("password_change_failed_weak_password", user_id=str(user.id), error=error_msg)
            raise ValueError(error_msg)

        # Update password
        user.password_hash = hash_password(new_password)
        user.updated_at = datetime.now(timezone.utc)
        await user.save()

        # Revoke all existing sessions for security
        await UserSession.find(UserSession.user_id == user.id).delete()

        logger.info("password_changed", user_id=str(user.id))

    @staticmethod
    async def setup_totp(user: User) -> tuple[str, str, list[str]]:
        """
        Set up TOTP (2FA) for a user.

        Args:
            user: User object

        Returns:
            tuple: (totp_secret, qr_code_data_uri, backup_codes)
        """
        # Generate TOTP secret
        totp_secret = pyotp.random_base32()

        # Create TOTP URI for QR code
        totp_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
            name=user.email,
            issuer_name=settings.app_name,
        )

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)

        # Convert QR code to data URI
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        qr_code_data_uri = f"data:image/png;base64,{img_str}"

        # Generate backup codes
        backup_codes = generate_backup_codes()

        # Save TOTP secret and hashed backup codes (but don't enable yet)
        user.totp_secret = totp_secret
        user.backup_codes = [hash_backup_code(code) for code in backup_codes]
        user.updated_at = datetime.now(timezone.utc)
        await user.save()

        logger.info("totp_setup_initiated", user_id=str(user.id))

        return totp_secret, qr_code_data_uri, backup_codes

    @staticmethod
    async def enable_totp(user: User, totp_code: str) -> None:
        """
        Enable TOTP after verifying the code works.

        Args:
            user: User object
            totp_code: TOTP code to verify

        Raises:
            InvalidTOTPError: If TOTP code is invalid
            ValueError: If TOTP not set up
        """
        if not user.totp_secret:
            raise ValueError("TOTP not set up for this user")

        # Verify TOTP code
        if not await AuthService.verify_totp(user, totp_code):
            logger.warning("totp_enable_failed_invalid_code", user_id=str(user.id))
            raise InvalidTOTPError("Invalid TOTP code")

        # Enable TOTP
        user.totp_enabled = True
        user.updated_at = datetime.now(timezone.utc)
        await user.save()

        logger.info("totp_enabled", user_id=str(user.id))

    @staticmethod
    async def disable_totp(user: User, password: str) -> None:
        """
        Disable TOTP for a user after verifying password.

        Args:
            user: User object
            password: User password for verification

        Raises:
            InvalidCredentialsError: If password is incorrect
        """
        # Verify password
        if not verify_password(password, user.password_hash):
            logger.warning("totp_disable_failed_invalid_password", user_id=str(user.id))
            raise InvalidCredentialsError("Invalid password")

        # Disable TOTP and clear secrets
        user.totp_enabled = False
        user.totp_secret = None
        user.backup_codes = []
        user.updated_at = datetime.now(timezone.utc)
        await user.save()

        logger.info("totp_disabled", user_id=str(user.id))

    @staticmethod
    async def verify_totp(user: User, code: str) -> bool:
        """
        Verify a TOTP code or backup code.

        Args:
            user: User object
            code: TOTP code or backup code to verify

        Returns:
            True if code is valid, False otherwise
        """
        if not user.totp_secret:
            return False

        # Try TOTP code first
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):  # Allow 1 time step tolerance
            return True

        # Try backup codes
        clean_code = code.replace("-", "")
        for hashed_code in user.backup_codes:
            if verify_password(clean_code, hashed_code):
                # Remove used backup code
                user.backup_codes.remove(hashed_code)
                await user.save()
                logger.info("backup_code_used", user_id=str(user.id), remaining=len(user.backup_codes))
                return True

        return False

    @staticmethod
    async def refresh_access_token(refresh_token: str) -> tuple[str, User]:
        """
        Generate a new access token from a refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            tuple: (new_access_token, user)

        Raises:
            AuthenticationError: If refresh token is invalid
        """
        # Decode refresh token
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            logger.warning("refresh_token_invalid")
            raise AuthenticationError("Invalid refresh token")

        # Get user
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token payload")

        user = await User.get(PydanticObjectId(user_id))
        if not user or not user.is_active:
            logger.warning("refresh_token_user_not_found_or_inactive", user_id=user_id)
            raise AuthenticationError("Invalid refresh token")

        # Generate new access token
        access_token = create_access_token(data={"sub": str(user.id), "email": user.email})

        logger.info("access_token_refreshed", user_id=str(user.id))
        return access_token, user

    @staticmethod
    async def logout(token_jti: str) -> None:
        """
        Logout user by revoking session.

        Args:
            token_jti: JWT ID of the token to revoke
        """
        # Delete session
        session = await UserSession.find_one(UserSession.token_jti == token_jti)
        if session:
            await session.delete()
            logger.info("user_logout", user_id=str(session.user_id))

    @staticmethod
    async def get_user_sessions(user_id: PydanticObjectId) -> list[UserSession]:
        """
        Get all active sessions for a user.

        Args:
            user_id: User ID

        Returns:
            List of active sessions
        """
        sessions = await UserSession.find(UserSession.user_id == user_id).to_list()
        return sessions

    @staticmethod
    async def revoke_session(session_id: PydanticObjectId, user_id: PydanticObjectId) -> None:
        """
        Revoke a specific session.

        Args:
            session_id: Session ID to revoke
            user_id: User ID (for authorization check)

        Raises:
            ValueError: If session not found or doesn't belong to user
        """
        session = await UserSession.get(session_id)
        if not session:
            raise ValueError("Session not found")

        if session.user_id != user_id:
            raise ValueError("Session does not belong to user")

        await session.delete()
        logger.info("session_revoked", session_id=str(session_id), user_id=str(user_id))

    @staticmethod
    async def get_current_user_from_token(token: str) -> Optional[User]:
        """
        Get user from JWT token.

        Args:
            token: JWT access token

        Returns:
            User object or None if invalid
        """
        payload = decode_token(token)
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        try:
            user = await User.get(PydanticObjectId(user_id))
            if user and user.is_active:
                return user
        except Exception as e:
            logger.warning("get_user_from_token_failed", error=str(e))

        return None

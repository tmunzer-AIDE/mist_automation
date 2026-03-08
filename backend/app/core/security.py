"""
Security utilities for authentication, password hashing, and JWT token management.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import bcrypt
from jose import JWTError, jwt
import secrets
import string
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """
    Validate password against security policy.
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if len(password) < settings.min_password_length:
        return False, f"Password must be at least {settings.min_password_length} characters long"
    
    if settings.require_uppercase and not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    
    if settings.require_lowercase and not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    
    if settings.require_digits and not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit"
    
    if settings.require_special_chars and not any(c in string.punctuation for c in password):
        return False, "Password must contain at least one special character"
    
    return True, None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> tuple[str, str]:
    """
    Create a JWT access token.
    
    Args:
        data: Payload data to encode in the token
        expires_delta: Optional custom expiration time
    
    Returns:
        Tuple of (encoded JWT token, token JTI)
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.access_token_expire_hours)
    
    # Generate JTI for token revocation
    token_jti = generate_token_id()
    
    # Add standard JWT claims
    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": token_jti,
    })
    
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt, token_jti


def create_refresh_token(data: dict) -> str:
    """
    Create a JWT refresh token with longer expiration.
    
    Args:
        data: Payload data to encode in the token
    
    Returns:
        Encoded JWT refresh token
    """
    expires_delta = timedelta(days=settings.refresh_token_expire_days)
    to_encode = data.copy()
    to_encode["type"] = "refresh"  # Mark as refresh token
    
    return create_access_token(to_encode, expires_delta)


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token to decode
    
    Returns:
        Decoded token payload or None if invalid
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError as e:
        logger.warning("jwt_decode_failed", error=str(e))
        return None


def generate_token_id() -> str:
    """Generate a unique token ID (JTI) for JWT tokens."""
    return secrets.token_urlsafe(32)


def generate_backup_codes(count: int = 10) -> list[str]:
    """
    Generate backup codes for 2FA recovery.
    
    Args:
        count: Number of backup codes to generate
    
    Returns:
        List of backup codes (unhashed)
    """
    codes = []
    for _ in range(count):
        # Generate 8-character alphanumeric code
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        # Format as XXXX-XXXX for better readability
        formatted_code = f"{code[:4]}-{code[4:]}"
        codes.append(formatted_code)
    return codes


def hash_backup_code(code: str) -> str:
    """Hash a backup code for storage."""
    # Remove hyphens before hashing
    clean_code = code.replace("-", "")
    return hash_password(clean_code)


def verify_backup_code(plain_code: str, hashed_code: str) -> bool:
    """Verify a backup code against its hash."""
    clean_code = plain_code.replace("-", "")
    return verify_password(clean_code, hashed_code)


def generate_secret_key() -> str:
    """Generate a secure random secret key."""
    return secrets.token_urlsafe(64)


def encrypt_sensitive_data(data: str, key: Optional[str] = None) -> str:
    """
    Encrypt sensitive data (e.g., API tokens).
    Uses Fernet symmetric encryption.
    
    Args:
        data: Data to encrypt
        key: Optional encryption key (uses settings.secret_key if not provided)
    
    Returns:
        Encrypted data as base64 string
    """
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    import base64
    
    # Derive encryption key from secret
    encryption_key = key or settings.secret_key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'mist_automation_salt',  # In production, use a random salt per encryption
        iterations=100000,
        backend=default_backend(),
    )
    derived_key = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
    
    f = Fernet(derived_key)
    encrypted = f.encrypt(data.encode())
    return encrypted.decode()


def decrypt_sensitive_data(encrypted_data: str, key: Optional[str] = None) -> str:
    """
    Decrypt sensitive data.
    
    Args:
        encrypted_data: Encrypted data as base64 string
        key: Optional encryption key (uses settings.secret_key if not provided)
    
    Returns:
        Decrypted data
    """
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.backends import default_backend
    import base64
    
    # Derive encryption key from secret
    encryption_key = key or settings.secret_key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'mist_automation_salt',
        iterations=100000,
        backend=default_backend(),
    )
    derived_key = base64.urlsafe_b64encode(kdf.derive(encryption_key.encode()))
    
    f = Fernet(derived_key)
    decrypted = f.decrypt(encrypted_data.encode())
    return decrypted.decode()

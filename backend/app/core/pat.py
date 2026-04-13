"""
Personal Access Token helpers.

PATs are long-lived bearer tokens used by external MCP clients. They are
high-entropy random strings prefixed with ``mist_pat_`` for easy identification
in logs and by secret scanners. Only the SHA-256 hash is persisted.
"""

import hashlib
import secrets

PAT_PREFIX = "mist_pat_"
PAT_DISPLAY_PREFIX_LEN = len(PAT_PREFIX) + 4  # e.g. "mist_pat_AbCd"


def generate_pat() -> tuple[str, str, str]:
    """Generate a new PAT.

    Returns ``(plaintext, token_hash, token_prefix)``. The plaintext must be
    shown to the user exactly once and never persisted.
    """
    plaintext = PAT_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_pat(plaintext), plaintext[:PAT_DISPLAY_PREFIX_LEN]


def hash_pat(plaintext: str) -> str:
    """SHA-256 hex digest of the raw token."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def is_pat_token(token: str) -> bool:
    """Return True if ``token`` looks like a PAT (prefix check only)."""
    return token.startswith(PAT_PREFIX)

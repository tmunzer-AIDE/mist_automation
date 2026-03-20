"""Encrypt, decrypt, and mask sensitive OAuth fields in node configs.

Shared by webhook and ServiceNow nodes. Sensitive fields (client_secret,
password) are encrypted at rest via AES-256-GCM and masked in API responses.
"""

from __future__ import annotations

from copy import deepcopy

from app.core.security import decrypt_sensitive_data, encrypt_sensitive_data

# Fields that must be encrypted at rest
OAUTH_SENSITIVE_FIELDS = ("oauth2_client_secret", "oauth2_password")

# Auth-type keys that indicate OAuth is configured on a node
_AUTH_TYPE_KEYS = ("webhook_auth_type", "servicenow_auth_type")

# Also encrypt basic-auth password for ServiceNow nodes
_SERVICENOW_BASIC_FIELDS = ("servicenow_password",)


def _has_oauth(config: dict) -> bool:
    """Check if a node config has any OAuth auth type enabled."""
    return any(config.get(k) == "oauth2_password" for k in _AUTH_TYPE_KEYS)


def _has_servicenow_basic(config: dict) -> bool:
    """Check if a node config uses ServiceNow basic auth."""
    return config.get("servicenow_auth_type") in ("basic", None) and any(
        config.get(f) for f in _SERVICENOW_BASIC_FIELDS
    )


def _sensitive_fields_for(config: dict) -> tuple[str, ...]:
    """Return the set of sensitive field names applicable to this config."""
    fields: list[str] = []
    if _has_oauth(config):
        fields.extend(OAUTH_SENSITIVE_FIELDS)
    if _has_servicenow_basic(config):
        fields.extend(_SERVICENOW_BASIC_FIELDS)
    return tuple(fields)


def _all_sensitive_fields() -> tuple[str, ...]:
    """All fields that could ever be sensitive, for masking."""
    return OAUTH_SENSITIVE_FIELDS + _SERVICENOW_BASIC_FIELDS


def _looks_encrypted(value: str) -> bool:
    """Heuristic: AES-256-GCM output is base64url, minimum ~60 chars."""
    return len(value) > 50 and not any(c in value for c in " \n\t")


def encrypt_node_secrets(config: dict) -> dict:
    """Encrypt sensitive fields in-place. Returns the config."""
    for field in _sensitive_fields_for(config):
        value = config.get(field)
        if value and not _looks_encrypted(value):
            config[field] = encrypt_sensitive_data(value)
    return config


def decrypt_node_secrets(config: dict) -> dict:
    """Decrypt sensitive fields. Returns a **copy** — original is not mutated."""
    result = deepcopy(config)
    for field in _all_sensitive_fields():
        value = result.get(field)
        if value and _looks_encrypted(value):
            try:
                result[field] = decrypt_sensitive_data(value)
            except Exception:
                pass  # may already be plaintext during migration
    return result


def mask_node_secrets(config: dict) -> dict:
    """Replace sensitive values with ``*_set`` booleans for API responses."""
    for field in _all_sensitive_fields():
        value = config.get(field)
        config[f"{field}_set"] = bool(value)
        config.pop(field, None)
    return config


def merge_node_secrets(new_config: dict, existing_config: dict) -> dict:
    """Preserve existing encrypted values when frontend sends empty fields."""
    for field in _all_sensitive_fields():
        new_value = new_config.get(field)
        if not new_value:
            existing = existing_config.get(field)
            if existing:
                new_config[field] = existing
    return new_config

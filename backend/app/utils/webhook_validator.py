"""
Webhook validation utilities.

Provides validation for:
- Webhook signatures (HMAC)
- Webhook payload structure
- Mist webhook types
- Replay attack protection
"""

import hmac
import hashlib
import json
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timedelta


class WebhookValidationError(Exception):
    """Raised when webhook validation fails."""
    pass


# Supported Mist webhook types
MIST_WEBHOOK_TYPES = {
    # Alarm webhooks
    "alarm": [
        "ap_offline",
        "ap_online",
        "switch_offline",
        "switch_online",
        "gateway_offline",
        "gateway_online",
        "ap_restarted",
        "switch_restarted",
        "gateway_restarted",
        "ap_configured",
        "switch_configured",
        "gateway_configured",
        "ap_disconnected",
        "switch_disconnected",
        "gateway_disconnected",
    ],
    
    # Audit webhooks
    "audit": [
        "config_changed",
        "site_config_changed",
        "org_config_changed",
        "device_config_changed",
        "wlan_config_changed",
        "network_config_changed",
    ],
    
    # Device events
    "device-events": [
        "device_claimed",
        "device_unclaimed",
        "device_assigned",
        "device_unassigned",
        "device_upgraded",
    ],
    
    # Client events
    "client-join": [
        "client_connected",
        "client_disconnected",
    ],
    
    # Zone events
    "zone": [
        "zone_entered",
        "zone_exited",
    ],
    
    # Asset events
    "asset-raw": [
        "asset_detected",
    ],
}


def validate_webhook_signature(
    payload_body: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256"
) -> Tuple[bool, Optional[str]]:
    """
    Validate webhook signature using HMAC.
    
    Args:
        payload_body: Raw webhook payload body (bytes)
        signature: Signature from webhook header
        secret: Shared secret for signature verification
        algorithm: Hash algorithm (default: sha256)
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> payload = b'{"event": "test"}'
        >>> secret = "my_secret_key"
        >>> sig = generate_webhook_signature(payload, secret)
        >>> valid, error = validate_webhook_signature(payload, sig, secret)
        >>> valid
        True
    """
    if not payload_body:
        return False, "Payload body is required"
        
    if not signature:
        return False, "Signature is required"
        
    if not secret:
        return False, "Secret is required"
        
    try:
        # Handle different signature formats
        # Format 1: sha256=<signature>
        if "=" in signature:
            parts = signature.split("=", 1)
            if len(parts) == 2:
                algorithm = parts[0]
                signature = parts[1]
                
        # Compute expected signature
        hash_func = getattr(hashlib, algorithm, None)
        if hash_func is None:
            return False, f"Unsupported hash algorithm: {algorithm}"
            
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload_body,
            hash_func
        ).hexdigest()
        
        # Compare signatures (constant-time comparison)
        if not hmac.compare_digest(signature, expected_signature):
            return False, "Signature validation failed"
            
        return True, None
        
    except Exception as e:
        return False, f"Error validating signature: {str(e)}"


def generate_webhook_signature(
    payload_body: bytes,
    secret: str,
    algorithm: str = "sha256"
) -> str:
    """
    Generate HMAC signature for webhook payload.
    
    Args:
        payload_body: Raw webhook payload body (bytes)
        secret: Shared secret for signature generation
        algorithm: Hash algorithm (default: sha256)
        
    Returns:
        Signature string
        
    Example:
        >>> payload = b'{"event": "test"}'
        >>> sig = generate_webhook_signature(payload, "my_secret")
        >>> len(sig) == 64  # SHA256 produces 64-character hex string
        True
    """
    hash_func = getattr(hashlib, algorithm)
    signature = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hash_func
    ).hexdigest()
    return signature


def validate_webhook_timestamp(
    timestamp: Optional[int],
    max_age_seconds: int = 300
) -> Tuple[bool, Optional[str]]:
    """
    Validate webhook timestamp to prevent replay attacks.
    
    Args:
        timestamp: Unix timestamp from webhook
        max_age_seconds: Maximum age in seconds (default: 5 minutes)
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> import time
        >>> now = int(time.time())
        >>> valid, error = validate_webhook_timestamp(now)
        >>> valid
        True
    """
    if timestamp is None:
        return False, "Timestamp is required"
        
    try:
        # Use UTC for both times to avoid timezone issues
        webhook_time = datetime.utcfromtimestamp(timestamp)
        current_time = datetime.utcnow()
        age = (current_time - webhook_time).total_seconds()
        
        if age < 0:
            return False, "Webhook timestamp is in the future"
            
        if age > max_age_seconds:
            return False, f"Webhook is too old (age: {int(age)}s, max: {max_age_seconds}s)"
            
        return True, None
        
    except (ValueError, OSError) as e:
        return False, f"Invalid timestamp: {str(e)}"


def validate_mist_webhook_type(webhook_type: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Mist webhook type.
    
    Args:
        webhook_type: Webhook type to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> valid, error = validate_mist_webhook_type("alarm")
        >>> valid
        True
    """
    if not webhook_type:
        return False, "Webhook type is required"
        
    # Check if it's a valid category
    if webhook_type in MIST_WEBHOOK_TYPES:
        return True, None
        
    # Check if it's a specific event type
    for category, events in MIST_WEBHOOK_TYPES.items():
        if webhook_type in events:
            return True, None
            
    return False, f"Invalid Mist webhook type: {webhook_type}"


def validate_webhook_payload(
    payload: Dict[str, Any],
    required_fields: Optional[list[str]] = None
) -> Tuple[bool, list[str]]:
    """
    Validate webhook payload structure.
    
    Args:
        payload: Webhook payload dictionary
        required_fields: List of required field paths (dot notation)
        
    Returns:
        Tuple of (is_valid, list_of_errors)
        
    Example:
        >>> payload = {"event": {"type": "alarm"}, "device": {"id": "123"}}
        >>> required = ["event.type", "device.id"]
        >>> valid, errors = validate_webhook_payload(payload, required)
        >>> valid
        True
    """
    errors = []
    
    if not isinstance(payload, dict):
        return False, ["Payload must be a dictionary"]
        
    if required_fields:
        for field_path in required_fields:
            value = get_nested_value(payload, field_path)
            if value is None:
                errors.append(f"Missing required field: {field_path}")
                
    return len(errors) == 0, errors


def validate_mist_alarm_payload(payload: Dict[str, Any]) -> Tuple[bool, list[str]]:
    """
    Validate Mist alarm webhook payload structure.
    
    Args:
        payload: Alarm webhook payload
        
    Returns:
        Tuple of (is_valid, list_of_errors)
        
    Example:
        >>> payload = {
        ...     "topic": "alarms",
        ...     "events": [{"type": "ap_offline", "site_id": "123"}]
        ... }
        >>> valid, errors = validate_mist_alarm_payload(payload)
        >>> valid
        True
    """
    errors = []
    
    # Check required top-level fields
    required_fields = ["topic", "events"]
    for field in required_fields:
        if field not in payload:
            errors.append(f"Missing required field: {field}")
            
    # Validate topic
    topic = payload.get("topic")
    if topic and topic not in ("alarms", "audits", "device-events", "client-join", "zone", "asset-raw"):
        errors.append(f"Invalid topic: {topic}")
        
    # Validate events array
    events = payload.get("events", [])
    if not isinstance(events, list):
        errors.append("'events' must be a list")
    elif len(events) == 0:
        errors.append("'events' cannot be empty")
    else:
        for idx, event in enumerate(events):
            if not isinstance(event, dict):
                errors.append(f"Event {idx} must be a dictionary")
                continue
                
            # Check for event type
            if "type" not in event:
                errors.append(f"Event {idx}: missing 'type' field")
                
    return len(errors) == 0, errors


def get_nested_value(data: Dict[str, Any], field_path: str) -> Any:
    """
    Extract value from nested dictionary using dot notation.
    
    Args:
        data: Source dictionary
        field_path: Dot-separated path (e.g., "event.device.name")
        
    Returns:
        The value at the specified path, or None if not found
    """
    if not field_path:
        return None
        
    keys = field_path.split(".")
    value = data
    
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
            
        if value is None:
            return None
            
    return value


def parse_webhook_payload(
    payload_body: bytes,
    content_type: str = "application/json"
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Parse webhook payload based on content type.
    
    Args:
        payload_body: Raw webhook payload body
        content_type: Content type header value
        
    Returns:
        Tuple of (is_valid, parsed_payload, error_message)
        
    Example:
        >>> payload = b'{"event": "test"}'
        >>> valid, parsed, error = parse_webhook_payload(payload)
        >>> valid
        True
        >>> parsed["event"]
        "test"
    """
    if not payload_body:
        return False, None, "Payload body is empty"
        
    try:
        if "json" in content_type.lower():
            parsed = json.loads(payload_body)
            return True, parsed, None
        else:
            return False, None, f"Unsupported content type: {content_type}"
            
    except json.JSONDecodeError as e:
        return False, None, f"Invalid JSON payload: {str(e)}"
    except Exception as e:
        return False, None, f"Error parsing payload: {str(e)}"


def validate_webhook_request(
    payload_body: bytes,
    signature: Optional[str] = None,
    secret: Optional[str] = None,
    timestamp: Optional[int] = None,
    content_type: str = "application/json",
    max_age_seconds: int = 300,
    validate_signature: bool = True
) -> Tuple[bool, Optional[Dict[str, Any]], list[str]]:
    """
    Comprehensive webhook request validation.
    
    Args:
        payload_body: Raw webhook payload body
        signature: Signature from webhook header
        secret: Shared secret for signature verification
        timestamp: Unix timestamp from webhook
        content_type: Content type header value
        max_age_seconds: Maximum webhook age in seconds
        validate_signature: Whether to validate signature
        
    Returns:
        Tuple of (is_valid, parsed_payload, list_of_errors)
        
    Example:
        >>> payload = b'{"topic": "alarms", "events": [{"type": "ap_offline"}]}'
        >>> valid, parsed, errors = validate_webhook_request(
        ...     payload,
        ...     validate_signature=False
        ... )
        >>> valid
        True
    """
    errors = []
    
    # Parse payload
    valid, parsed_payload, error = parse_webhook_payload(payload_body, content_type)
    if not valid:
        errors.append(error)
        return False, None, errors
        
    # Validate signature if required
    if validate_signature:
        if not signature or not secret:
            errors.append("Signature validation enabled but signature or secret is missing")
        else:
            valid, error = validate_webhook_signature(payload_body, signature, secret)
            if not valid:
                errors.append(f"Signature validation failed: {error}")
                
    # Validate timestamp if provided
    if timestamp is not None:
        valid, error = validate_webhook_timestamp(timestamp, max_age_seconds)
        if not valid:
            errors.append(f"Timestamp validation failed: {error}")
            
    return len(errors) == 0, parsed_payload, errors

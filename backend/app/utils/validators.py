"""
Input validation utilities.

Provides common validation functions for:
- Cron expressions
- URLs and email addresses
- Passwords
- IP addresses
- JSON data
- Templates
- Filters
"""

import re
import json
import ipaddress
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from croniter import croniter
from datetime import datetime


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def validate_email(email: str) -> Tuple[bool, Optional[str]]:
    """
    Validate email address format.
    
    Args:
        email: Email address to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> valid, error = validate_email("user@example.com")
        >>> valid
        True
    """
    if not email:
        return False, "Email address is required"
        
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        return False, "Invalid email address format"
        
    if len(email) > 254:
        return False, "Email address is too long (max 254 characters)"
        
    # Check local part (before @)
    local_part = email.split('@')[0]
    if len(local_part) > 64:
        return False, "Email local part is too long (max 64 characters)"
        
    return True, None


def validate_password(
    password: str,
    min_length: int = 8,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_digit: bool = True,
    require_special: bool = True
) -> Tuple[bool, Optional[str]]:
    """
    Validate password strength.
    
    Args:
        password: Password to validate
        min_length: Minimum password length
        require_uppercase: Require at least one uppercase letter
        require_lowercase: Require at least one lowercase letter
        require_digit: Require at least one digit
        require_special: Require at least one special character
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> valid, error = validate_password("SecurePass123!")
        >>> valid
        True
    """
    if not password:
        return False, "Password is required"
        
    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters long"
        
    if require_uppercase and not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
        
    if require_lowercase and not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
        
    if require_digit and not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
        
    if require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
        
    return True, None


def validate_url(url: str, allowed_schemes: Optional[List[str]] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate URL format.
    
    Args:
        url: URL to validate
        allowed_schemes: List of allowed URL schemes (default: ['http', 'https'])
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> valid, error = validate_url("https://example.com")
        >>> valid
        True
    """
    if not url:
        return False, "URL is required"
        
    if allowed_schemes is None:
        allowed_schemes = ['http', 'https']
        
    try:
        parsed = urlparse(url)
        
        if not parsed.scheme:
            return False, "URL must include a scheme (e.g., https://)"
            
        if parsed.scheme not in allowed_schemes:
            return False, f"URL scheme must be one of: {', '.join(allowed_schemes)}"
            
        if not parsed.netloc:
            return False, "URL must include a domain"
            
        return True, None
        
    except Exception as e:
        return False, f"Invalid URL format: {str(e)}"


def validate_ip_address(ip: str, version: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate IP address format.
    
    Args:
        ip: IP address to validate
        version: IP version (4 or 6), or None for either
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> valid, error = validate_ip_address("192.168.1.1")
        >>> valid
        True
    """
    if not ip:
        return False, "IP address is required"
        
    try:
        ip_obj = ipaddress.ip_address(ip)
        
        if version == 4 and ip_obj.version != 4:
            return False, "Must be an IPv4 address"
            
        if version == 6 and ip_obj.version != 6:
            return False, "Must be an IPv6 address"
            
        return True, None
        
    except ValueError as e:
        return False, f"Invalid IP address: {str(e)}"


def validate_cron_expression(
    expression: str,
    allow_seconds: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Validate cron expression format.
    
    Args:
        expression: Cron expression to validate
        allow_seconds: Whether to allow 6-field cron expressions (with seconds)
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> valid, error = validate_cron_expression("0 0 * * *")
        >>> valid
        True
    """
    if not expression:
        return False, "Cron expression is required"
        
    try:
        # Validate using croniter
        croniter(expression)
        
        # Check field count
        fields = expression.split()
        
        if allow_seconds:
            if len(fields) not in (5, 6):
                return False, "Cron expression must have 5 or 6 fields"
        else:
            if len(fields) != 5:
                return False, "Cron expression must have exactly 5 fields"
                
        return True, None
        
    except Exception as e:
        return False, f"Invalid cron expression: {str(e)}"


def validate_timezone(timezone: str) -> Tuple[bool, Optional[str]]:
    """
    Validate timezone string.
    
    Args:
        timezone: Timezone string (e.g., "America/New_York")
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> valid, error = validate_timezone("America/New_York")
        >>> valid
        True
    """
    if not timezone:
        return False, "Timezone is required"
        
    try:
        import zoneinfo
        zoneinfo.ZoneInfo(timezone)
        return True, None
    except Exception:
        try:
            import pytz
            pytz.timezone(timezone)
            return True, None
        except Exception as e:
            return False, f"Invalid timezone: {str(e)}"


def validate_json(data: str) -> Tuple[bool, Optional[str], Optional[Any]]:
    """
    Validate JSON string.
    
    Args:
        data: JSON string to validate
        
    Returns:
        Tuple of (is_valid, error_message, parsed_data)
        
    Example:
        >>> valid, error, parsed = validate_json('{"key": "value"}')
        >>> valid
        True
    """
    if not data:
        return False, "JSON data is required", None
        
    try:
        parsed = json.loads(data)
        return True, None, parsed
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}", None


def validate_filter_config(filter_config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate filter configuration.
    
    Args:
        filter_config: Filter configuration dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> config = {"field": "type", "operator": "equals", "value": "alarm"}
        >>> valid, error = validate_filter_config(config)
        >>> valid
        True
    """
    if not isinstance(filter_config, dict):
        return False, "Filter config must be a dictionary"
        
    # Check for nested filter group
    if "filters" in filter_config:
        filters = filter_config.get("filters", [])
        if not isinstance(filters, list):
            return False, "Filter group 'filters' must be a list"
            
        logic = filter_config.get("logic", "and")
        if logic not in ("and", "or"):
            return False, "Filter group 'logic' must be 'and' or 'or'"
            
        # Validate each nested filter
        for idx, nested_filter in enumerate(filters):
            valid, error = validate_filter_config(nested_filter)
            if not valid:
                return False, f"Filter {idx}: {error}"
                
        return True, None
        
    # Validate single filter
    required_fields = ["field", "operator"]
    for field in required_fields:
        if field not in filter_config:
            return False, f"Filter config missing required field: {field}"
            
    # Validate operator
    valid_operators = [
        "equals", "contains", "starts_with", "ends_with", "regex",
        "greater_than", "less_than", "between",
        "is_true", "is_false",
        "in_list", "not_in_list"
    ]
    
    operator = filter_config.get("operator")
    if operator not in valid_operators:
        return False, f"Invalid operator '{operator}'. Must be one of: {', '.join(valid_operators)}"
        
    # Validate value for operators that require it
    if operator not in ("is_true", "is_false"):
        if "value" not in filter_config:
            return False, f"Operator '{operator}' requires a 'value' field"
            
    # Validate specific operators
    if operator == "between":
        value = filter_config.get("value")
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return False, "Operator 'between' requires a list of exactly 2 values"
            
    if operator in ("in_list", "not_in_list"):
        value = filter_config.get("value")
        if not isinstance(value, (list, tuple)):
            return False, f"Operator '{operator}' requires a list value"
            
    # Validate source
    source = filter_config.get("source", "webhook")
    if source not in ("webhook", "api_result"):
        return False, f"Invalid source '{source}'. Must be 'webhook' or 'api_result'"
        
    return True, None


def validate_action_config(action_config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate action configuration.
    
    Args:
        action_config: Action configuration dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Example:
        >>> config = {"type": "api_get", "endpoint": "devices"}
        >>> valid, error = validate_action_config(config)
        >>> valid
        True
    """
    if not isinstance(action_config, dict):
        return False, "Action config must be a dictionary"
        
    # Check required fields
    if "type" not in action_config:
        return False, "Action config missing required field: type"
        
    # Validate action type
    valid_types = [
        "api_get", "api_post", "api_put", "api_delete",
        "slack", "servicenow", "pagerduty", "webhook"
    ]
    
    action_type = action_config.get("type")
    if action_type not in valid_types:
        return False, f"Invalid action type '{action_type}'. Must be one of: {', '.join(valid_types)}"
        
    # Validate API actions
    if action_type.startswith("api_"):
        if "endpoint" not in action_config:
            return False, f"Action type '{action_type}' requires an 'endpoint' field"
            
    # Validate notification actions
    if action_type in ("slack", "servicenow", "pagerduty", "webhook"):
        if "config" not in action_config:
            return False, f"Action type '{action_type}' requires a 'config' field"
            
    # Validate on_failure
    on_failure = action_config.get("on_failure", "stop")
    if on_failure not in ("stop", "continue"):
        return False, f"Invalid on_failure value '{on_failure}'. Must be 'stop' or 'continue'"
        
    return True, None


def validate_workflow_config(workflow_config: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate complete workflow configuration.
    
    Args:
        workflow_config: Workflow configuration dictionary
        
    Returns:
        Tuple of (is_valid, list_of_errors)
        
    Example:
        >>> config = {
        ...     "name": "Test Workflow",
        ...     "trigger": {"type": "webhook", "webhook_type": "alarm"},
        ...     "filters": [],
        ...     "actions": []
        ... }
        >>> valid, errors = validate_workflow_config(config)
        >>> valid
        True
    """
    errors = []
    
    if not isinstance(workflow_config, dict):
        return False, ["Workflow config must be a dictionary"]
        
    # Validate required fields
    required_fields = ["name", "trigger"]
    for field in required_fields:
        if field not in workflow_config:
            errors.append(f"Missing required field: {field}")
            
    # Validate name
    name = workflow_config.get("name", "")
    if not name or not name.strip():
        errors.append("Workflow name cannot be empty")
    elif len(name) > 100:
        errors.append("Workflow name is too long (max 100 characters)")
        
    # Validate trigger
    trigger = workflow_config.get("trigger", {})
    if not isinstance(trigger, dict):
        errors.append("Trigger must be a dictionary")
    else:
        if "type" not in trigger:
            errors.append("Trigger missing required field: type")
        else:
            trigger_type = trigger.get("type")
            if trigger_type not in ("webhook", "cron"):
                errors.append(f"Invalid trigger type '{trigger_type}'. Must be 'webhook' or 'cron'")
                
            if trigger_type == "webhook":
                if "webhook_type" not in trigger:
                    errors.append("Webhook trigger requires 'webhook_type' field")
                    
            if trigger_type == "cron":
                if "cron_expression" not in trigger:
                    errors.append("Cron trigger requires 'cron_expression' field")
                else:
                    cron_expr = trigger.get("cron_expression")
                    valid, error = validate_cron_expression(cron_expr)
                    if not valid:
                        errors.append(f"Invalid cron expression: {error}")
                        
                if "timezone" in trigger:
                    tz = trigger.get("timezone")
                    valid, error = validate_timezone(tz)
                    if not valid:
                        errors.append(f"Invalid timezone: {error}")
                        
    # Validate filters
    filters = workflow_config.get("filters", [])
    if not isinstance(filters, list):
        errors.append("Filters must be a list")
    else:
        for idx, filter_config in enumerate(filters):
            valid, error = validate_filter_config(filter_config)
            if not valid:
                errors.append(f"Filter {idx}: {error}")
                
    # Validate actions
    actions = workflow_config.get("actions", [])
    if not isinstance(actions, list):
        errors.append("Actions must be a list")
    else:
        for idx, action_config in enumerate(actions):
            valid, error = validate_action_config(action_config)
            if not valid:
                errors.append(f"Action {idx}: {error}")
                
    # Validate status
    status = workflow_config.get("status", "draft")
    if status not in ("enabled", "disabled", "draft"):
        errors.append(f"Invalid status '{status}'. Must be 'enabled', 'disabled', or 'draft'")
        
    # Validate sharing
    sharing = workflow_config.get("sharing", "private")
    if sharing not in ("private", "read-only", "read-write"):
        errors.append(f"Invalid sharing '{sharing}'. Must be 'private', 'read-only', or 'read-write'")
        
    # Validate timeout
    timeout = workflow_config.get("timeout_seconds")
    if timeout is not None:
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            errors.append("Timeout must be a positive number")
        elif timeout > 3600:
            errors.append("Timeout cannot exceed 3600 seconds (1 hour)")
            
    return len(errors) == 0, errors


def sanitize_string(
    value: str,
    max_length: Optional[int] = None,
    allowed_chars: Optional[str] = None,
    strip: bool = True
) -> str:
    """
    Sanitize string input.
    
    Args:
        value: String to sanitize
        max_length: Maximum length to truncate to
        allowed_chars: Regex pattern of allowed characters
        strip: Whether to strip whitespace
        
    Returns:
        Sanitized string
        
    Example:
        >>> sanitize_string("  Hello World!  ", max_length=10)
        "Hello Worl"
    """
    if not value:
        return ""
        
    result = value
    
    if strip:
        result = result.strip()
        
    if allowed_chars:
        # Keep only allowed characters
        result = re.sub(f"[^{allowed_chars}]", "", result)
        
    if max_length and len(result) > max_length:
        result = result[:max_length]
        
    return result

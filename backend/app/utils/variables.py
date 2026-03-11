"""
Variable substitution engine for workflow actions and notifications.

Supports template variables using {{variable_name}} syntax:
- Webhook payload: {{event.device.name}}
- API responses: {{device_stats.uptime}}
- Workflow context: {{workflow.name}}, {{execution.timestamp}}
- Environment variables: {{env.VAR_NAME}}
"""

import re
from datetime import datetime, timezone
from typing import Any

from jinja2 import (
    ChainableUndefined,
    StrictUndefined,
    TemplateSyntaxError,
    UndefinedError,
)
from jinja2.sandbox import SandboxedEnvironment


class VariableSubstitutionError(Exception):
    """Raised when variable substitution fails."""


def get_nested_value(data: dict[str, Any], path: str, default: Any = None) -> Any:
    """
    Safely extract value from nested dictionary using dot notation.

    Args:
        data: Source dictionary
        path: Dot-separated path (e.g., "event.device.name")
        default: Default value if path not found

    Returns:
        The value at the specified path, or default if not found
    """
    if not path or not isinstance(data, dict):
        return default

    keys = path.split(".")
    value = data

    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return default

        if value is None:
            return default

    return value


def build_context(
    webhook_data: dict[str, Any] | None = None,
    api_results: dict[str, Any] | None = None,
    workflow_context: dict[str, Any] | None = None,
    include_env: bool = False,
) -> dict[str, Any]:
    """
    Build context dictionary for variable substitution.

    Args:
        webhook_data: Webhook payload data
        api_results: Results from API calls (keyed by save_as name)
        workflow_context: Workflow execution context
        include_env: Whether to include environment variables

    Returns:
        Context dictionary with all available variables

    Example:
        >>> context = build_context(
        ...     webhook_data={"event": {"type": "alarm"}},
        ...     workflow_context={"workflow": {"name": "Test"}}
        ... )
        >>> context["event"]["type"]
        "alarm"
    """
    context = {}

    # Add webhook data (root level)
    if webhook_data:
        context.update(webhook_data)

    # Add API results
    if api_results:
        for key, value in api_results.items():
            context[key] = value

    # Add workflow context
    if workflow_context:
        context.update(workflow_context)

    # Add safe environment variables under 'env' namespace
    if include_env:
        from app.config import settings

        context["env"] = {
            "APP_NAME": settings.app_name,
            "ENVIRONMENT": settings.environment,
        }

    # Add utility functions and values
    context["now"] = datetime.now(timezone.utc)
    context["now_iso"] = datetime.now(timezone.utc).isoformat()
    context["now_timestamp"] = int(datetime.now(timezone.utc).timestamp())

    return context


def substitute_variables(
    template: str,
    webhook_data: dict[str, Any] | None = None,
    api_results: dict[str, Any] | None = None,
    workflow_context: dict[str, Any] | None = None,
    include_env: bool = False,
    strict: bool = False,
) -> str:
    """
    Substitute template variables with actual values.

    Args:
        template: Template string with {{variable}} placeholders
        webhook_data: Webhook payload data
        api_results: Results from API calls
        workflow_context: Workflow execution context
        include_env: Whether to include environment variables
        strict: If True, raise error on undefined variables; if False, leave undefined

    Returns:
        String with variables substituted

    Raises:
        VariableSubstitutionError: If template is invalid or variables are undefined (in strict mode)

    Example:
        >>> template = "Device {{event.device.name}} went offline"
        >>> webhook_data = {"event": {"device": {"name": "AP-01"}}}
        >>> substitute_variables(template, webhook_data=webhook_data)
        "Device AP-01 went offline"
    """
    if not template:
        return template

    # Build context
    context = build_context(
        webhook_data=webhook_data, api_results=api_results, workflow_context=workflow_context, include_env=include_env
    )

    # Create sandboxed Jinja2 environment
    if strict:
        env = SandboxedEnvironment(undefined=StrictUndefined)
    else:
        env = SandboxedEnvironment(undefined=ChainableUndefined)

    try:
        # Render template
        jinja_template = env.from_string(template)
        result = jinja_template.render(context)
        return result

    except TemplateSyntaxError as e:
        raise VariableSubstitutionError(f"Template syntax error at line {e.lineno}: {e.message}") from e
    except UndefinedError as e:
        raise VariableSubstitutionError(f"Undefined variable in template: {e.message}") from e
    except Exception as e:
        raise VariableSubstitutionError(f"Error substituting variables: {str(e)}") from e


def substitute_in_dict(
    data: dict[str, Any],
    webhook_data: dict[str, Any] | None = None,
    api_results: dict[str, Any] | None = None,
    workflow_context: dict[str, Any] | None = None,
    include_env: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    """
    Recursively substitute variables in dictionary values.

    Args:
        data: Dictionary with potential template strings
        webhook_data: Webhook payload data
        api_results: Results from API calls
        workflow_context: Workflow execution context
        include_env: Whether to include environment variables
        strict: If True, raise error on undefined variables

    Returns:
        Dictionary with variables substituted

    Example:
        >>> data = {
        ...     "message": "Device {{device.name}} failed",
        ...     "details": {"severity": "{{alarm.severity}}"}
        ... }
        >>> webhook_data = {
        ...     "device": {"name": "AP-01"},
        ...     "alarm": {"severity": "critical"}
        ... }
        >>> result = substitute_in_dict(data, webhook_data=webhook_data)
        >>> result["message"]
        "Device AP-01 failed"
    """
    result = {}

    for key, value in data.items():
        if isinstance(value, str):
            # Substitute variables in string
            result[key] = substitute_variables(
                value,
                webhook_data=webhook_data,
                api_results=api_results,
                workflow_context=workflow_context,
                include_env=include_env,
                strict=strict,
            )
        elif isinstance(value, dict):
            # Recursively process nested dictionaries
            result[key] = substitute_in_dict(
                value,
                webhook_data=webhook_data,
                api_results=api_results,
                workflow_context=workflow_context,
                include_env=include_env,
                strict=strict,
            )
        elif isinstance(value, list):
            # Process lists
            result[key] = substitute_in_list(
                value,
                webhook_data=webhook_data,
                api_results=api_results,
                workflow_context=workflow_context,
                include_env=include_env,
                strict=strict,
            )
        else:
            # Keep other types as-is
            result[key] = value

    return result


def substitute_in_list(
    data: list,
    webhook_data: dict[str, Any] | None = None,
    api_results: dict[str, Any] | None = None,
    workflow_context: dict[str, Any] | None = None,
    include_env: bool = False,
    strict: bool = False,
) -> list:
    """
    Recursively substitute variables in list items.

    Args:
        data: List with potential template strings
        webhook_data: Webhook payload data
        api_results: Results from API calls
        workflow_context: Workflow execution context
        include_env: Whether to include environment variables
        strict: If True, raise error on undefined variables

    Returns:
        List with variables substituted
    """
    result = []

    for item in data:
        if isinstance(item, str):
            # Substitute variables in string
            result.append(
                substitute_variables(
                    item,
                    webhook_data=webhook_data,
                    api_results=api_results,
                    workflow_context=workflow_context,
                    include_env=include_env,
                    strict=strict,
                )
            )
        elif isinstance(item, dict):
            # Recursively process dictionaries
            result.append(
                substitute_in_dict(
                    item,
                    webhook_data=webhook_data,
                    api_results=api_results,
                    workflow_context=workflow_context,
                    include_env=include_env,
                    strict=strict,
                )
            )
        elif isinstance(item, list):
            # Recursively process nested lists
            result.append(
                substitute_in_list(
                    item,
                    webhook_data=webhook_data,
                    api_results=api_results,
                    workflow_context=workflow_context,
                    include_env=include_env,
                    strict=strict,
                )
            )
        else:
            # Keep other types as-is
            result.append(item)

    return result


def extract_variables(template: str) -> list[str]:
    """
    Extract all variable names from a template string.

    Args:
        template: Template string with {{variable}} placeholders

    Returns:
        List of variable names found in template

    Example:
        >>> extract_variables("Device {{device.name}} has {{alarm.type}}")
        ["device.name", "alarm.type"]
    """
    if not template:
        return []

    # Match {{variable}} patterns
    pattern = r"\{\{\s*([^}]+?)\s*\}\}"
    matches = re.findall(pattern, template)

    # Clean up variable names (remove filters and whitespace)
    variables = []
    for match in matches:
        # Split on | to remove Jinja2 filters
        var_name = match.split("|")[0].strip()
        if var_name and var_name not in variables:
            variables.append(var_name)

    return variables


def validate_template(template: str) -> tuple[bool, str | None]:
    """
    Validate template syntax without rendering.

    Args:
        template: Template string to validate

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> valid, error = validate_template("Hello {{name}}")
        >>> valid
        True
        >>> valid, error = validate_template("Hello {{name")
        >>> valid
        False
    """
    if not template:
        return True, None

    try:
        env = SandboxedEnvironment()
        env.from_string(template)
        return True, None
    except TemplateSyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.message}"
    except Exception as e:
        return False, str(e)


def preview_substitution(template: str, context: dict[str, Any]) -> dict[str, Any]:
    """
    Preview variable substitution with detailed information.

    Args:
        template: Template string
        context: Context dictionary for substitution

    Returns:
        Dictionary with preview information

    Example:
        >>> template = "Device {{device.name}}"
        >>> context = {"device": {"name": "AP-01"}}
        >>> preview = preview_substitution(template, context)
        >>> preview["result"]
        "Device AP-01"
    """
    # Extract variables
    variables = extract_variables(template)

    # Validate template
    is_valid, error = validate_template(template)

    if not is_valid:
        return {"valid": False, "error": error, "variables": variables}

    # Try substitution
    try:
        env = SandboxedEnvironment(undefined=ChainableUndefined)
        jinja_template = env.from_string(template)
        result = jinja_template.render(context)

        # Map variables to their values
        variable_values = {}
        for var in variables:
            value = get_nested_value(context, var, "<undefined>")
            variable_values[var] = value

        return {"valid": True, "result": result, "variables": variables, "variable_values": variable_values}
    except Exception as e:
        return {"valid": False, "error": str(e), "variables": variables}

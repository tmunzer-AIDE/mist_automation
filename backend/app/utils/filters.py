"""
Filter evaluation engine for workflow filtering.

Supports:
- String operations: equals, contains, starts_with, ends_with, regex
- Numeric operations: equals, greater_than, less_than, between
- Boolean operations: is_true, is_false
- List operations: in_list, not_in_list
- Nested field access with dot notation
- AND/OR filter chaining
"""

import re
from typing import Any

from app.models.workflow import FilterOperator, FilterLogic


class FilterEvaluationError(Exception):
    """Raised when filter evaluation fails."""


def get_nested_value(data: dict[str, Any], field_path: str) -> Any:
    """
    Extract value from nested dictionary using dot notation.

    Args:
        data: Source dictionary
        field_path: Dot-separated path (e.g., "event.device.name")

    Returns:
        The value at the specified path, or None if not found

    Example:
        >>> data = {"event": {"device": {"name": "AP-01"}}}
        >>> get_nested_value(data, "event.device.name")
        "AP-01"
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


def evaluate_string_filter(
    actual_value: Any,
    operator: FilterOperator,
    expected_value: Any
) -> bool:
    """
    Evaluate string-based filter operations.

    Args:
        actual_value: Value to test
        operator: Filter operator
        expected_value: Value to compare against

    Returns:
        True if filter passes, False otherwise
    """
    # Convert to string for comparison
    actual_str = str(actual_value) if actual_value is not None else ""
    expected_str = str(expected_value) if expected_value is not None else ""

    if operator == FilterOperator.EQUALS:
        return actual_str == expected_str

    elif operator == FilterOperator.CONTAINS:
        return expected_str in actual_str

    elif operator == FilterOperator.STARTS_WITH:
        return actual_str.startswith(expected_str)

    elif operator == FilterOperator.ENDS_WITH:
        return actual_str.endswith(expected_str)

    elif operator == FilterOperator.REGEX:
        try:
            return bool(re.search(expected_str, actual_str))
        except re.error as e:
            raise FilterEvaluationError(
                f"Invalid regex pattern '{expected_str}': {e}"
            ) from e

    return False


def evaluate_numeric_filter(
    actual_value: Any,
    operator: FilterOperator,
    expected_value: Any
) -> bool:
    """
    Evaluate numeric filter operations.

    Args:
        actual_value: Value to test
        operator: Filter operator
        expected_value: Value to compare against (or list for 'between')

    Returns:
        True if filter passes, False otherwise
    """
    try:
        # Convert to numeric types
        if isinstance(actual_value, (int, float)):
            actual_num = actual_value
        else:
            actual_num = float(actual_value)
    except (ValueError, TypeError):
        return False

    if operator == FilterOperator.EQUALS:
        try:
            expected_num = float(expected_value)
            return actual_num == expected_num
        except (ValueError, TypeError):
            return False

    elif operator == FilterOperator.GREATER_THAN:
        try:
            expected_num = float(expected_value)
            return actual_num > expected_num
        except (ValueError, TypeError):
            return False

    elif operator == FilterOperator.LESS_THAN:
        try:
            expected_num = float(expected_value)
            return actual_num < expected_num
        except (ValueError, TypeError):
            return False

    elif operator == FilterOperator.BETWEEN:
        if not isinstance(expected_value, (list, tuple)) or len(expected_value) != 2:
            raise FilterEvaluationError(
                f"'between' operator requires a list of two values, got: {expected_value}"
            )
        try:
            min_val = float(expected_value[0])
            max_val = float(expected_value[1])
            return min_val <= actual_num <= max_val
        except (ValueError, TypeError) as e:
            raise FilterEvaluationError(
                f"Invalid numeric values for 'between': {e}"
            ) from e

    return False


def evaluate_boolean_filter(
    actual_value: Any,
    operator: FilterOperator
) -> bool:
    """
    Evaluate boolean filter operations.

    Args:
        actual_value: Value to test
        operator: Filter operator

    Returns:
        True if filter passes, False otherwise
    """
    # Convert to boolean
    if isinstance(actual_value, bool):
        actual_bool = actual_value
    elif isinstance(actual_value, str):
        actual_bool = actual_value.lower() in ("true", "1", "yes", "on")
    elif isinstance(actual_value, (int, float)):
        actual_bool = bool(actual_value)
    else:
        actual_bool = bool(actual_value)

    if operator == FilterOperator.IS_TRUE:
        return actual_bool is True

    elif operator == FilterOperator.IS_FALSE:
        return actual_bool is False

    return False


def evaluate_list_filter(
    actual_value: Any,
    operator: FilterOperator,
    expected_value: Any
) -> bool:
    """
    Evaluate list-based filter operations.

    Args:
        actual_value: Value to test
        operator: Filter operator
        expected_value: List to check against

    Returns:
        True if filter passes, False otherwise
    """
    if not isinstance(expected_value, (list, tuple)):
        raise FilterEvaluationError(
            f"List operators require a list value, got: {type(expected_value).__name__}"
        )

    if operator == FilterOperator.IN_LIST:
        return actual_value in expected_value

    elif operator == FilterOperator.NOT_IN_LIST:
        return actual_value not in expected_value

    return False


def evaluate_single_filter(
    filter_config: dict[str, Any],
    data: dict[str, Any],
    source: str = "webhook"
) -> bool:
    """
    Evaluate a single filter against data.

    Args:
        filter_config: Filter configuration with 'field', 'operator', and 'value'
        data: Data to filter against
        source: Data source identifier (for secondary filters)

    Returns:
        True if filter passes, False otherwise

    Raises:
        FilterEvaluationError: If filter configuration is invalid

    Example:
        >>> filter_config = {
        ...     "field": "event.type",
        ...     "operator": "equals",
        ...     "value": "ap_offline"
        ... }
        >>> data = {"event": {"type": "ap_offline"}}
        >>> evaluate_single_filter(filter_config, data)
        True
    """
    # Validate filter config
    if not isinstance(filter_config, dict):
        raise FilterEvaluationError("Filter config must be a dictionary")

    required_fields = ["field", "operator"]
    for field in required_fields:
        if field not in filter_config:
            raise FilterEvaluationError(f"Filter config missing required field: {field}")

    field_path = filter_config["field"]
    operator_str = filter_config["operator"]
    expected_value = filter_config.get("value")
    filter_source = filter_config.get("source", "webhook")

    # Validate operator
    try:
        operator = FilterOperator(operator_str)
    except ValueError as exc:
        raise FilterEvaluationError(
            f"Invalid operator '{operator_str}'. Must be one of: "
            f"{', '.join([op.value for op in FilterOperator])}"
        ) from exc

    # Skip if source doesn't match (for secondary filters)
    if filter_source != source:
        return True

    # Extract actual value from data
    actual_value = get_nested_value(data, field_path)

    # Evaluate based on operator type
    try:
        if operator in (
            FilterOperator.EQUALS,
            FilterOperator.CONTAINS,
            FilterOperator.STARTS_WITH,
            FilterOperator.ENDS_WITH,
            FilterOperator.REGEX
        ):
            return evaluate_string_filter(actual_value, operator, expected_value)

        elif operator in (
            FilterOperator.GREATER_THAN,
            FilterOperator.LESS_THAN,
            FilterOperator.BETWEEN
        ):
            return evaluate_numeric_filter(actual_value, operator, expected_value)

        elif operator in (FilterOperator.IS_TRUE, FilterOperator.IS_FALSE):
            return evaluate_boolean_filter(actual_value, operator)

        elif operator in (FilterOperator.IN_LIST, FilterOperator.NOT_IN_LIST):
            return evaluate_list_filter(actual_value, operator, expected_value)

    except FilterEvaluationError:
        raise
    except Exception as e:
        raise FilterEvaluationError(f"Error evaluating filter: {e}") from e

    return False


def evaluate_filter_group(
    filter_group: list[dict[str, Any]] | dict[str, Any],
    data: dict[str, Any],
    logic: FilterLogic = FilterLogic.AND,
    source: str = "webhook"
) -> bool:
    """
    Evaluate a group of filters with AND/OR logic.

    Args:
        filter_group: List of filter configs or nested group
        data: Data to filter against
        logic: Logic to combine filters (AND or OR)
        source: Data source identifier

    Returns:
        True if filter group passes, False otherwise

    Example:
        >>> filters = [
        ...     {"field": "type", "operator": "equals", "value": "alarm"},
        ...     {"field": "severity", "operator": "in_list", "value": ["critical", "major"]}
        ... ]
        >>> data = {"type": "alarm", "severity": "critical"}
        >>> evaluate_filter_group(filters, data)
        True
    """
    # Handle empty filter list
    if not filter_group:
        return True

    # Handle nested group with explicit logic
    if isinstance(filter_group, dict):
        nested_logic = FilterLogic(filter_group.get("logic", "and"))
        nested_filters = filter_group.get("filters", [])
        return evaluate_filter_group(nested_filters, data, nested_logic, source)

    # Evaluate list of filters
    if not isinstance(filter_group, list):
        raise FilterEvaluationError("Filter group must be a list or dict")

    results = []
    for filter_config in filter_group:
        # Handle nested groups
        if isinstance(filter_config, dict) and "filters" in filter_config:
            result = evaluate_filter_group(filter_config, data, logic, source)
        else:
            result = evaluate_single_filter(filter_config, data, source)
        results.append(result)

    # Apply logic
    if logic == FilterLogic.AND:
        return all(results)
    elif logic == FilterLogic.OR:
        return any(results)
    else:
        raise FilterEvaluationError(f"Invalid logic: {logic}")


def evaluate_filters(
    filters: list[dict[str, Any]],
    data: dict[str, Any],
    source: str = "webhook"
) -> dict[str, Any]:
    """
    Evaluate all filters and return detailed results.

    Args:
        filters: List of filter configurations
        data: Data to filter against
        source: Data source identifier

    Returns:
        Dictionary with overall result and individual filter results

    Example:
        >>> filters = [
        ...     {"field": "type", "operator": "equals", "value": "alarm"}
        ... ]
        >>> data = {"type": "alarm"}
        >>> result = evaluate_filters(filters, data)
        >>> result["passed"]
        True
    """
    if not filters:
        return {
            "passed": True,
            "filter_results": [],
            "logic": "and"
        }

    filter_results = []

    for idx, filter_config in enumerate(filters):
        try:
            # Handle nested groups
            if isinstance(filter_config, dict) and "filters" in filter_config:
                passed = evaluate_filter_group(filter_config, data, source=source)
                filter_results.append({
                    "filter_index": idx,
                    "filter_type": "group",
                    "passed": passed,
                    "actual_value": None
                })
            else:
                field_path = filter_config.get("field", "")
                actual_value = get_nested_value(data, field_path)
                passed = evaluate_single_filter(filter_config, data, source)

                filter_results.append({
                    "filter_index": idx,
                    "filter_type": "single",
                    "field": field_path,
                    "operator": filter_config.get("operator"),
                    "expected_value": filter_config.get("value"),
                    "actual_value": actual_value,
                    "passed": passed
                })
        except FilterEvaluationError as e:
            filter_results.append({
                "filter_index": idx,
                "passed": False,
                "error": str(e)
            })

    # Overall result (all must pass)
    overall_passed = all(r["passed"] for r in filter_results)

    return {
        "passed": overall_passed,
        "filter_results": filter_results,
        "logic": "and"
    }


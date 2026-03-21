"""
Shared utilities for MCP server tool handlers.

Provides data pruning, truncation, and elicitation helpers to keep
tool responses compact for small LLM context windows.
"""

import json
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

MAX_VALUE_LEN = 500
MAX_DIFF_ENTRIES = 50
MAX_LIST_ITEMS = 50
MAX_PAYLOAD_LEN = 3000


def truncate_value(value: Any, max_len: int = MAX_VALUE_LEN) -> Any:
    """Truncate a string or repr of a value to max_len chars."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "..."
    return value


def prune_config(config: dict, max_keys: int = 30, max_value_len: int = MAX_VALUE_LEN) -> dict:
    """Prune a configuration dict: keep top-level keys, truncate values."""
    if not isinstance(config, dict):
        return config
    pruned: dict = {}
    for i, (k, v) in enumerate(config.items()):
        if i >= max_keys:
            pruned["__truncated__"] = f"{len(config) - max_keys} more keys"
            break
        if isinstance(v, str):
            pruned[k] = truncate_value(v, max_value_len)
        elif isinstance(v, dict):
            pruned[k] = f"{{...}} ({len(v)} keys)"
        elif isinstance(v, list):
            pruned[k] = f"[...] ({len(v)} items)"
        else:
            pruned[k] = v
    return pruned


def compact_results(items: list[dict], fields: list[str]) -> list[dict]:
    """Extract only the specified fields from each item in a list."""
    return [{f: item.get(f) for f in fields if f in item} for item in items]


def cap_list(items: list, limit: int = MAX_LIST_ITEMS) -> list:
    """Cap a list and note if truncated."""
    if len(items) <= limit:
        return items
    return items[:limit] + [{"__note__": f"{len(items) - limit} more items not shown"}]


def to_json(data: Any) -> str:
    """Serialize data to compact JSON, handling datetimes and ObjectIds."""

    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    return json.dumps(data, default=_default, ensure_ascii=False)


def get_nested_value(data: dict, path: str) -> Any:
    """Get a value from a nested dict using dot-notation path."""
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def extract_fields(config: dict, fields: list[str]) -> dict:
    """Extract specific dot-notation fields from a config dict."""
    result: dict = {}
    for field in fields:
        val = get_nested_value(config, field)
        if val is not None:
            result[field] = truncate_value(val)
    return result


async def elicit_confirmation(ctx: Any, description: str) -> bool:
    """Ask user for confirmation via MCP elicitation.

    Returns True if accepted. For in-process transports (where elicitation is
    not supported), auto-approves since the user already initiated the action
    via the UI.
    """
    try:
        result = await ctx.elicit(description)
        if result.action == "accept":
            return True
        raise ValueError(f"Action cancelled by user ({result.action})")
    except NotImplementedError:
        # In-process MCP transport does not support elicitation —
        # auto-approve since the user already triggered this via the UI
        logger.debug("elicitation_not_supported", description=description)
        return True

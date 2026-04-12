"""
Shared utilities for MCP server tool handlers.

Provides data pruning, truncation, and elicitation helpers to keep
tool responses compact for small LLM context windows.
"""

import asyncio
import contextvars
import json
import uuid
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ── Elicitation bridge ──────────────────────────────────────────────────────

# Set by the caller (e.g., _mcp_user_session) to indicate which WS channel
# to broadcast elicitation requests on. When unset, elicitation auto-approves.
elicitation_channel_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "elicitation_channel", default=None
)

# Pending elicitations awaiting user response, keyed by request_id.
# Each value is a (user_id, Future) tuple for ownership verification.
# NOTE: In-process state — requires single-worker deployment. Use Redis for multi-worker.
_pending_elicitations: dict[str, tuple[str | None, asyncio.Future[bool]]] = {}


def get_elicitation_owner(request_id: str) -> str | None:
    """Return the user_id that owns a pending elicitation, or None if not found."""
    entry = _pending_elicitations.get(request_id)
    if entry is None:
        return None
    return entry[0]


def resolve_elicitation(request_id: str, accepted: bool) -> bool:
    """Resolve a pending elicitation request with the user's decision.

    Returns True if the request was found and resolved.
    Caller should verify ownership via ``get_elicitation_owner()`` first.
    """
    entry = _pending_elicitations.pop(request_id, None)
    if entry is None:
        return False
    _user_id, future = entry
    if not future.done():
        future.set_result(accepted)
        return True
    return False


MAX_VALUE_LEN = 500
MAX_DIFF_ENTRIES = 50
MAX_LIST_ITEMS = 50
MAX_PAYLOAD_LEN = 3000


def truncate_value(value: Any, max_len: int = MAX_VALUE_LEN) -> Any:
    """Truncate a string or repr of a value to max_len chars."""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "..."
    return value


def _prune_value(
    value: Any,
    *,
    depth: int,
    max_depth: int,
    max_value_len: int,
    small_dict_threshold: int,
    inline: bool,
) -> Any:
    """Recursively prune a value.

    - `inline=True` recurses fully into dicts/lists (only scalars get truncated).
    - `inline=False` recurses up to `max_depth`; dicts with more than
      `small_dict_threshold` keys become a `"{...} (N keys)"` summary, and
      lists with more items become `"[...] (N items)"`.
    """
    if isinstance(value, str):
        return truncate_value(value, max_value_len)

    if isinstance(value, dict):
        if inline:
            return {
                k: _prune_value(
                    v,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_value_len=max_value_len,
                    small_dict_threshold=small_dict_threshold,
                    inline=True,
                )
                for k, v in value.items()
            }
        if depth >= max_depth or len(value) > small_dict_threshold:
            return f"{{...}} ({len(value)} keys)"
        return {
            k: _prune_value(
                v,
                depth=depth + 1,
                max_depth=max_depth,
                max_value_len=max_value_len,
                small_dict_threshold=small_dict_threshold,
                inline=False,
            )
            for k, v in value.items()
        }

    if isinstance(value, list):
        if inline:
            return [
                _prune_value(
                    v,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_value_len=max_value_len,
                    small_dict_threshold=small_dict_threshold,
                    inline=True,
                )
                for v in value
            ]
        if depth >= max_depth or len(value) > small_dict_threshold:
            return f"[...] ({len(value)} items)"
        return [
            _prune_value(
                v,
                depth=depth + 1,
                max_depth=max_depth,
                max_value_len=max_value_len,
                small_dict_threshold=small_dict_threshold,
                inline=False,
            )
            for v in value
        ]

    return value


def prune_config(
    config: dict,
    max_keys: int = 30,
    max_value_len: int = MAX_VALUE_LEN,
    inline_keys: set[str] | None = None,
    small_dict_threshold: int = 3,
    max_depth: int = 3,
) -> dict:
    """Prune a configuration dict for compact LLM-friendly rendering.

    - Strings are truncated to `max_value_len`.
    - Top-level dict is capped at `max_keys` entries; remainder summarized in `__truncated__`.
    - Nested dicts/lists with more than `small_dict_threshold` entries become
      `"{...} (N keys)"` / `"[...] (N items)"` summaries; smaller ones are rendered inline.
    - Keys listed in `inline_keys` are rendered in full depth (still truncating strings).
      Use this to surface fields the caller cares about regardless of size — e.g. fields
      from `BackupObject.changed_fields` when showing a backup version diff.
    """
    if not isinstance(config, dict):
        return config

    pruned: dict = {}
    inline_set = inline_keys or set()
    for i, (k, v) in enumerate(config.items()):
        if i >= max_keys:
            pruned["__truncated__"] = f"{len(config) - max_keys} more keys"
            break
        pruned[k] = _prune_value(
            v,
            depth=1,
            max_depth=max_depth,
            max_value_len=max_value_len,
            small_dict_threshold=small_dict_threshold,
            inline=k in inline_set,
        )
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


async def _elicit(payload: dict[str, Any], description: str, timeout: float) -> bool:
    """Core elicitation: broadcast payload via WS and wait for user response.

    Auto-approves when no WS channel is set (workflow AI agent nodes without a UI).
    """
    channel = elicitation_channel_var.get()
    if not channel:
        logger.debug("elicitation_auto_approved", description=description)
        return True

    from app.core.websocket import ws_manager
    from app.modules.mcp_server.server import mcp_user_id_var

    request_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    user_id = mcp_user_id_var.get()
    _pending_elicitations[request_id] = (user_id, future)

    payload["request_id"] = request_id
    await ws_manager.broadcast(channel, payload)
    logger.debug("elicitation_sent", request_id=request_id, channel=channel, description=description)

    try:
        accepted = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        _pending_elicitations.pop(request_id, None)
        raise ValueError("Confirmation timed out — user did not respond") from None
    except BaseException:
        _pending_elicitations.pop(request_id, None)
        raise

    if not accepted:
        raise ValueError(f"Action declined by user: {description}")
    return True


async def elicit_confirmation(ctx: Any, description: str, timeout: float = 120.0) -> bool:
    """Ask user for simple text confirmation via MCP elicitation."""
    return await _elicit(
        {"type": "elicitation", "description": description},
        description,
        timeout,
    )


async def elicit_restore_confirmation(
    ctx: Any,
    description: str,
    diff_data: dict[str, Any],
    timeout: float = 180.0,
) -> bool:
    """Ask user for restore confirmation with diff data via MCP elicitation."""
    return await _elicit(
        {
            "type": "elicitation",
            "description": description,
            "elicitation_type": "restore_confirm",
            "data": diff_data,
        },
        description,
        timeout,
    )

"""
Shared utilities for the backup module.
"""


def _diff_lists(a: list, b: list, path: str) -> list[dict]:
    """Per-index list diff — recurses into element dicts.

    For scalar / mixed-type lists we still emit a single ``modified`` entry
    so consumers that render opaque values keep working. For lists of dicts
    we emit per-index entries so the UI/LLM can see exactly which element(s)
    changed, which fields changed, or which elements were added/removed.
    """
    changes: list[dict] = []

    both_dict_lists = all(isinstance(x, dict) for x in a) and all(isinstance(x, dict) for x in b)
    if not both_dict_lists:
        if a != b:
            changes.append({"path": path, "type": "modified", "old": a, "new": b})
        return changes

    common = min(len(a), len(b))
    for i in range(common):
        changes.extend(deep_diff(a[i], b[i], f"{path}[{i}]"))
    for i in range(common, len(a)):
        changes.append({"path": f"{path}[{i}]", "type": "removed", "value": a[i]})
    for i in range(common, len(b)):
        changes.append({"path": f"{path}[{i}]", "type": "added", "value": b[i]})
    return changes


def deep_diff(a: dict, b: dict, path: str = "") -> list[dict]:
    """Recursively compare two dicts and return a list of changes.

    Each change has: ``path`` (dot-notation), ``type`` (added/removed/modified),
    and ``value``/``old``+``new`` depending on type.

    Lists-of-dicts are expanded per-index so UI/LLM consumers see exactly
    which element changed rather than a single opaque before/after blob.
    """
    changes, all_keys = [], set(a) | set(b)
    for key in all_keys:
        p = f"{path}.{key}" if path else key
        if key not in a:
            changes.append({"path": p, "type": "added", "value": b[key]})
        elif key not in b:
            changes.append({"path": p, "type": "removed", "value": a[key]})
        elif isinstance(a[key], dict) and isinstance(b[key], dict):
            changes.extend(deep_diff(a[key], b[key], p))
        elif isinstance(a[key], list) and isinstance(b[key], list):
            changes.extend(_diff_lists(a[key], b[key], p))
        elif a[key] != b[key]:
            changes.append({"path": p, "type": "modified", "old": a[key], "new": b[key]})
    return changes

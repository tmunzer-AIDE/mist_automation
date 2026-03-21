"""
Shared utilities for the backup module.
"""


def deep_diff(a: dict, b: dict, path: str = "") -> list[dict]:
    """Recursively compare two dicts and return a list of changes.

    Each change has: ``path`` (dot-notation), ``type`` (added/removed/modified),
    and ``value``/``old``+``new`` depending on type.
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
        elif a[key] != b[key]:
            changes.append({"path": p, "type": "modified", "old": a[key], "new": b[key]})
    return changes

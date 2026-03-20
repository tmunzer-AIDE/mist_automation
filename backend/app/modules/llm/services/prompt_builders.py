"""
Purpose-built prompt constructors for each LLM feature.

Each function returns a list of LLMMessage dicts (role + content) and is pure
(no I/O), making them easy to test in isolation.
"""

import json


def build_backup_summary_prompt(
    diff_entries: list[dict],
    object_type: str,
    object_name: str | None,
    old_version: int,
    new_version: int,
    event_type: str,
    changed_fields: list[str],
) -> list[dict[str, str]]:
    """Build prompt for backup change summarization."""
    system = (
        "You are a network configuration analyst for Juniper Mist. "
        "Summarize configuration changes concisely and explain their operational impact. "
        "Focus on what changed, why it might matter, and any risks. "
        "Use short paragraphs. Do not repeat the raw diff data — interpret it."
    )

    # Truncate diff for very large changes to avoid token overflow
    diff_text = json.dumps(diff_entries[:100], indent=2, default=str)
    if len(diff_entries) > 100:
        diff_text += f"\n... and {len(diff_entries) - 100} more changes"

    name_display = object_name or "(unnamed)"
    user = (
        f"A Mist **{object_type}** object named **{name_display}** was changed "
        f"(v{old_version} → v{new_version}, event: {event_type}).\n\n"
        f"**Changed fields**: {', '.join(changed_fields) if changed_fields else 'N/A'}\n\n"
        f"**Detailed diff**:\n```json\n{diff_text}\n```\n\n"
        "Please summarize what was changed and explain the operational impact."
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

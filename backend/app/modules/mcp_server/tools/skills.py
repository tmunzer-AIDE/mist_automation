"""
MCP tool: activate_skill — loads the full instructions for a named Agent Skill.
"""

from pathlib import Path
from typing import Annotated
from xml.sax.saxutils import escape

import structlog
from fastmcp.exceptions import ToolError
from pydantic import Field

from app.modules.mcp_server.server import mcp, mcp_thread_id_var
from app.modules.mcp_server.tools.utils import is_placeholder

logger = structlog.get_logger(__name__)


def _validate_skill_name(name: str) -> str:
    """Validate and normalize skill name input."""
    skill_name = name.strip()
    if not skill_name:
        raise ToolError("name is required")
    if is_placeholder(skill_name):
        raise ToolError("name must be a real skill name, not a placeholder")
    return skill_name


async def _resolve_required_mcp_config_id(skill) -> str | None:
    """Return the MCP config ID required for a skill, if any.

    Resolution order:
    1) Skill-level binding (direct-imported skills)
    2) Repo-level binding (git-imported skills)
    """
    if skill.mcp_config_id:
        return str(skill.mcp_config_id)

    if skill.git_repo_id:
        from app.modules.llm.models import SkillGitRepo

        repo = await SkillGitRepo.get(skill.git_repo_id)
        if repo and repo.mcp_config_id:
            return str(repo.mcp_config_id)

    return None


async def _is_skill_allowed_in_current_chat(skill) -> bool:
    """Check whether a skill is allowed in the current MCP chat context."""
    required_mcp_config_id = await _resolve_required_mcp_config_id(skill)
    if not required_mcp_config_id:
        return True

    thread_id = mcp_thread_id_var.get()
    if not thread_id:
        return False

    from beanie import PydanticObjectId

    from app.modules.llm.models import ConversationThread

    try:
        thread_oid = PydanticObjectId(thread_id)
    except Exception:
        return False

    thread = await ConversationThread.get(thread_oid)
    if not thread:
        return False

    return required_mcp_config_id in set(thread.mcp_config_ids or [])


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False})
async def activate_skill(
    name: Annotated[
        str,
        Field(
            description=(
                "Exact skill name from the skill catalog (case-sensitive). "
                "Use only names listed in your system prompt; do not use placeholders or guesses."
            )
        ),
    ]
) -> str:
    """Load the full instructions for a named Agent Skill.

    Call this tool when the user's request matches a skill's description. Prefer activate_skill over
    reading general documentation when a named skill applies — skills are kept in sync with current
    project conventions and contain the exact procedure the platform expects you to follow.

    Returns the skill's markdown instructions wrapped in <skill_content> tags, along with a list of
    any bundled resource files in the skill directory.
    """
    from app.modules.llm.models import Skill
    from app.modules.llm.services.skills_service import (
        find_app_skill_dir,
        get_skill_effective_mcp_id,
        list_skill_resources,
        parse_skill_md,
    )

    skill_name = _validate_skill_name(name)

    skill = await Skill.find_one(Skill.name == skill_name, Skill.enabled == True)  # noqa: E712
    source_label: str
    if skill:
        # Enforce MCP binding: if skill is bound to an MCP server, that server must be active in the thread
        effective_mcp_id = await get_skill_effective_mcp_id(skill=skill)
        if effective_mcp_id:
            from app.modules.llm.services.skills_service import ORPHANED_SKILL_SENTINEL

            # Handle orphaned skills (git repo was deleted)
            if effective_mcp_id == ORPHANED_SKILL_SENTINEL:
                raise ToolError(
                    f"Skill '{skill_name}' cannot be activated: the git repository it was imported from has been deleted"
                )

            # mcp_thread_id_var has default=None, so .get() never raises LookupError
            thread_id = mcp_thread_id_var.get()
            active_mcp_ids: set[str] = set()
            if thread_id:
                from beanie import PydanticObjectId
                from bson.errors import InvalidId

                from app.modules.llm.models import ConversationThread

                try:
                    thread_object_id = PydanticObjectId(thread_id)
                except (InvalidId, TypeError, ValueError) as exc:
                    raise ToolError(
                        "Invalid conversation context: unable to determine the active MCP servers"
                    ) from exc

                thread = await ConversationThread.get(thread_object_id)
                if thread and thread.mcp_config_ids:
                    active_mcp_ids = set(thread.mcp_config_ids)

            if effective_mcp_id not in active_mcp_ids:
                # Provide a more helpful error for external MCP clients (no thread context)
                if not thread_id:
                    raise ToolError(
                        f"Skill '{skill_name}' requires an MCP server binding and can only be used "
                        f"in an in-app conversation with that MCP server enabled. "
                        f"External MCP clients (using Personal Access Tokens) cannot activate MCP-bound skills."
                    )
                raise ToolError(
                    f"Skill '{skill_name}' requires MCP server that is not enabled for this conversation"
                )

        skill_dir = Path(skill.local_path)
        source_label = str(skill.local_path)
    else:
        # Fallback: built-in app skills from dedicated folder are always available.
        skill_dir = find_app_skill_dir(skill_name)
        if not skill_dir:
            raise ToolError(f"Skill '{skill_name}' not found or not enabled")
        source_label = str(skill_dir)

    skill_file = skill_dir / "SKILL.md"

    if not skill_file.exists():
        logger.error("skill_file_missing", skill=skill_name, path=str(skill_file))
        raise ToolError(f"Skill '{skill_name}' SKILL.md file is missing from the server filesystem")

    try:
        _, _, body = parse_skill_md(skill_file)
    except ValueError as exc:
        raise ToolError(f"Skill '{skill_name}' could not be loaded: {exc}") from exc

    resources = list_skill_resources(skill_dir)
    resources_block = ""
    if resources:
        resource_lines = "\n".join(f"  <file>{escape(str(r))}</file>" for r in resources)
        resources_block = f"\n<skill_resources>\n{resource_lines}\n</skill_resources>"

    return (
        f'<skill_content name="{escape(skill_name)}">\n'
        f"{escape(body)}\n\n"
        f"Skill directory: {escape(source_label)}"
        f"{resources_block}\n"
        f"</skill_content>"
    )

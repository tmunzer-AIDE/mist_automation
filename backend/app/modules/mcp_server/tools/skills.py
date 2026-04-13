"""
MCP tool: activate_skill — loads the full instructions for a named Agent Skill.
"""

from pathlib import Path
from typing import Annotated
from xml.sax.saxutils import escape

import structlog
from fastmcp.exceptions import ToolError
from pydantic import Field

from app.modules.mcp_server.server import mcp
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
    from app.modules.llm.services.skills_service import list_skill_resources, parse_skill_md

    skill_name = _validate_skill_name(name)

    skill = await Skill.find_one(Skill.name == skill_name, Skill.enabled == True)  # noqa: E712
    if not skill:
        raise ToolError(f"Skill '{skill_name}' not found or not enabled")

    skill_dir = Path(skill.local_path)
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
        f"Skill directory: {escape(str(skill.local_path))}"
        f"{resources_block}\n"
        f"</skill_content>"
    )

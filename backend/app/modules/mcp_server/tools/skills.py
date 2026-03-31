"""
MCP tool: activate_skill — loads the full instructions for a named Agent Skill.
"""

from pathlib import Path

import structlog

from app.modules.mcp_server.server import mcp

logger = structlog.get_logger(__name__)


@mcp.tool()
async def activate_skill(name: str) -> str:
    """Load the full instructions for a named Agent Skill.

    Call this tool when the user's request matches a skill's description.
    The skill catalog in your system prompt lists available skill names.

    Returns the skill's markdown instructions wrapped in <skill_content> tags,
    along with a list of any bundled resource files in the skill directory.
    """
    from app.modules.llm.models import Skill
    from app.modules.llm.services.skills_service import list_skill_resources, parse_skill_md

    skill = await Skill.find_one(Skill.name == name, Skill.enabled == True)  # noqa: E712
    if not skill:
        return f"Skill '{name}' not found or not enabled."

    skill_dir = Path(skill.local_path)
    skill_file = skill_dir / "SKILL.md"

    if not skill_file.exists():
        logger.error("skill_file_missing", skill=name, path=str(skill_file))
        return f"Skill '{name}' SKILL.md file is missing from the server filesystem."

    try:
        _, _, body = parse_skill_md(skill_file)
    except ValueError as exc:
        return f"Skill '{name}' could not be loaded: {exc}"

    resources = list_skill_resources(skill_dir)
    resources_block = ""
    if resources:
        resource_lines = "\n".join(f"  <file>{r}</file>" for r in resources)
        resources_block = f"\n<skill_resources>\n{resource_lines}\n</skill_resources>"

    return (
        f'<skill_content name="{name}">\n'
        f"{body}\n\n"
        f"Skill directory: {skill.local_path}"
        f"{resources_block}\n"
        f"</skill_content>"
    )

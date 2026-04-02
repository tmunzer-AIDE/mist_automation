"""
Agent Skills utilities: filesystem scan, SKILL.md parsing, catalog builder, and git helpers.
"""

import asyncio
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

import structlog
import yaml

logger = structlog.get_logger(__name__)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".svn"}


def parse_skill_md(path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file.

    Returns (name, description, body) where body is the markdown content after
    the YAML frontmatter, stripped of leading/trailing whitespace.

    Raises ValueError if frontmatter is absent, unclosed, unparseable,
    or missing the required 'description' field.
    """
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError("SKILL.md missing YAML frontmatter")

    end = content.find("\n---", 3)
    if end == -1:
        raise ValueError("SKILL.md frontmatter not closed")

    yaml_text = content[3:end].strip()
    body = content[end + 4:].strip()

    # Standard parse first; fall back for unquoted values containing colons
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        fixed = re.sub(r"^(\w[\w-]*):\s*(.+:.+)$", r'\1: "\2"', yaml_text, flags=re.MULTILINE)
        try:
            data = yaml.safe_load(fixed)
        except yaml.YAMLError as exc:
            raise ValueError(f"SKILL.md frontmatter is unparseable: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")

    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()

    if not description:
        raise ValueError("SKILL.md missing required 'description' field")

    return (name, description, body)


def scan_for_skills(base_dir: Path, max_depth: int = 6) -> list[Path]:
    """Recursively find SKILL.md files within base_dir up to max_depth levels deep.

    Returns a list of paths to each SKILL.md file found.
    The skill directory is the parent of each returned path.
    """
    results: list[Path] = []

    def _walk(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            for entry in sorted(current.iterdir()):
                if entry.is_file() and entry.name == "SKILL.md":
                    results.append(entry)
                elif entry.is_dir() and entry.name not in _SKIP_DIRS:
                    _walk(entry, depth + 1)
        except PermissionError:
            pass

    if base_dir.is_dir():
        _walk(base_dir, 0)

    return results


def list_skill_resources(skill_dir: Path) -> list[str]:
    """List non-SKILL.md files in a skill directory as relative path strings."""
    if not skill_dir.is_dir():
        return []
    return sorted(
        str(item.relative_to(skill_dir))
        for item in skill_dir.rglob("*")
        if item.is_file() and item.name != "SKILL.md"
    )


def append_skills_to_messages(messages: list[dict], catalog: str) -> list[dict]:
    """Return a new messages list with the skills catalog appended to the system message.

    Non-mutating: returns a new list with a copied system message dict.
    No-op (returns original list) if catalog is empty, messages is empty,
    or the first message is not 'system'.
    """
    if not catalog or not messages:
        return messages
    if messages[0].get("role") == "system":
        updated = {**messages[0], "content": messages[0]["content"] + "\n\n" + catalog}
        return [updated, *messages[1:]]
    return messages


async def build_skills_catalog() -> str:
    """Return an XML catalog of enabled skills for injection into LLM system prompts.

    Returns an empty string if no skills are enabled (so callers can skip injection).
    """
    from app.modules.llm.models import Skill  # local import to avoid circular dep

    skills = await Skill.find(Skill.enabled == True).to_list()  # noqa: E712
    if not skills:
        return ""

    lines = ["<available_skills>"]
    for skill in skills:
        lines.append("  <skill>")
        lines.append(f"    <name>{escape(skill.name)}</name>")
        lines.append(f"    <description>{escape(skill.description)}</description>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    lines.append(
        "\nWhen a task matches a skill's description, call the activate_skill tool "
        "with the skill's name to load its full instructions before proceeding."
    )

    return "\n".join(lines)


# ── Git helpers ───────────────────────────────────────────────────────────────


def _auth_url(url: str, token: str | None) -> str:
    """Embed a token into an HTTPS URL for authentication."""
    if not token:
        return url
    from urllib.parse import quote, urlparse, urlunparse

    parsed = urlparse(url)
    netloc = f"oauth2:{quote(token, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


async def clone_repo(url: str, token: str | None, branch: str, dest: Path) -> None:
    """Clone a git repository to dest (runs in a thread to avoid blocking the event loop)."""
    import git

    auth = _auth_url(url, token)

    def _clone() -> None:
        dest.mkdir(parents=True, exist_ok=True)
        repo = git.Repo.clone_from(auth, str(dest), branch=branch, depth=1)
        if token:
            # Remove token from .git/config immediately after clone
            repo.remotes.origin.set_url(url)

    await asyncio.to_thread(_clone)


async def pull_repo(repo_path: Path, url: str, token: str | None) -> None:
    """Pull latest changes in an existing git clone (runs in a thread)."""
    import git

    auth = _auth_url(url, token)

    def _pull() -> None:
        repo = git.Repo(str(repo_path))
        origin = repo.remotes.origin
        if token:
            original_url = origin.url
            origin.set_url(auth)
        try:
            origin.pull()
        finally:
            if token:
                origin.set_url(original_url)  # restore clean URL, token never persisted

    await asyncio.to_thread(_pull)


def remove_dir(path: Path) -> None:
    """Remove a directory tree, silently ignore if it doesn't exist."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


async def sync_skills_from_repo(
    repo_id: str,
    repo_path: Path,
) -> tuple[int, int]:
    """Scan a cloned repo, upsert Skill documents for all discovered SKILL.md files.

    Returns (added, updated) counts.
    """
    from beanie import PydanticObjectId

    from app.modules.llm.models import Skill

    skill_files = scan_for_skills(repo_path)
    added = updated = 0

    for skill_file in skill_files:
        skill_dir = skill_file.parent
        error_msg: str | None = None
        name = desc = ""

        try:
            name, desc, _ = parse_skill_md(skill_file)
        except ValueError as exc:
            error_msg = str(exc)
            logger.warning("skill_parse_error", path=str(skill_file), error=error_msg)

        if not name:
            name = skill_dir.name  # fallback to directory name

        existing = await Skill.find_one(
            Skill.git_repo_id == PydanticObjectId(repo_id),
            Skill.local_path == str(skill_dir),
        )

        now = datetime.now(timezone.utc)

        if existing:
            existing.name = name
            existing.description = desc or existing.description
            existing.error = error_msg
            existing.last_synced_at = now if not error_msg else existing.last_synced_at
            existing.update_timestamp()
            await existing.save()
            updated += 1
        else:
            if not desc:
                continue  # skip skills with no description (not useful in catalog)
            skill = Skill(
                name=name,
                description=desc,
                source="git",
                local_path=str(skill_dir),
                enabled=True,
                git_repo_id=PydanticObjectId(repo_id),
                error=error_msg,
                last_synced_at=now if not error_msg else None,
            )
            try:
                await skill.insert()
                added += 1
            except Exception as exc:
                if "11000" in str(exc) or "duplicate" in str(exc).lower():
                    logger.warning("skill_name_collision", name=name, repo_id=repo_id, path=str(skill_dir))
                else:
                    raise

    return added, updated

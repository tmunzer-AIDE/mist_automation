"""
Agent Skills utilities: filesystem scan, SKILL.md parsing, catalog builder, and git helpers.
"""

import asyncio
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import NamedTuple
from xml.sax.saxutils import escape

import structlog
import yaml

logger = structlog.get_logger(__name__)

# Sentinel value returned when a skill references a deleted git repo.
# This value will never match any active MCP config ID, effectively blocking the skill.
ORPHANED_SKILL_SENTINEL = "<orphaned:repo_deleted>"

# Footer appended to skills catalog. Also used by llm.py to strip old catalogs before rebuilding.
SKILLS_CATALOG_FOOTER = (
    "When a task matches a skill's description, call the activate_skill tool "
    "with the skill's name to load its full instructions before proceeding."
)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".svn"}
_APP_SKILLS_CACHE_TTL_SECONDS = 30.0
_app_skills_cache: dict[str, tuple[float, list["SkillCatalogEntry"]]] = {}
# Cache for name → directory mapping (same TTL, shared invalidation with _app_skills_cache)
_app_skills_index_cache: dict[str, tuple[float, dict[str, Path]]] = {}
# Track orphaned skills that have already been logged (avoid log spam on hot paths)
_logged_orphaned_skills: set[str] = set()


class SkillCatalogEntry(NamedTuple):
    name: str
    description: str


def parse_skill_md(path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file.

    Returns (name, description, body) where body is the markdown content after
    the YAML frontmatter, stripped of leading/trailing whitespace.

    Raises ValueError if frontmatter is absent, unclosed, unparseable,
    or missing the required 'description' field.
    """
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
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


def get_app_skills_dir() -> Path:
    """Return the dedicated built-in app skills directory.

    Resolution order:
    1) `APP_SKILLS_DIR`/`app_skills_dir` setting if provided
    2) code-owned default: `<repo>/backend/app/modules/llm/skills`
    """
    from app.config import settings

    configured = str(getattr(settings, "app_skills_dir", "") or "").strip()
    if configured:
        return Path(configured)

    # Keep built-in skills in the application code path (not runtime-mounted /skills volume).
    return Path(__file__).resolve().parents[1] / "skills"


def load_app_skill_entries(base_dir: Path | None = None) -> list[SkillCatalogEntry]:
    """Load built-in app skill metadata from SKILL.md files.

    Invalid skill files are skipped with a warning.

    Results are cached per directory for a short TTL to avoid repeated
    recursive filesystem scans in hot request paths.
    """
    skills_dir = base_dir or get_app_skills_dir()
    cache_key = str(skills_dir.resolve())
    cached = _app_skills_cache.get(cache_key)
    now = monotonic()
    if cached and now - cached[0] < _APP_SKILLS_CACHE_TTL_SECONDS:
        return list(cached[1])

    entries: list[SkillCatalogEntry] = []

    for skill_file in scan_for_skills(skills_dir):
        try:
            name, description, _ = parse_skill_md(skill_file)
        except ValueError as exc:
            logger.warning("app_skill_parse_error", path=str(skill_file), error=str(exc))
            continue

        if not name:
            name = skill_file.parent.name

        entries.append(SkillCatalogEntry(name=name, description=description))

    _app_skills_cache[cache_key] = (now, list(entries))
    return list(entries)


def clear_app_skills_cache() -> None:
    """Clear in-memory cache for built-in app skill metadata."""
    _app_skills_cache.clear()
    _app_skills_index_cache.clear()


def _build_app_skills_index(base_dir: Path) -> dict[str, Path]:
    """Build a name → directory index for all valid app skills."""
    index: dict[str, Path] = {}
    for skill_file in scan_for_skills(base_dir):
        try:
            name, _, _ = parse_skill_md(skill_file)
        except ValueError:
            continue
        if not name:
            name = skill_file.parent.name
        index[name] = skill_file.parent
    return index


def find_app_skill_dir(skill_name: str, base_dir: Path | None = None) -> Path | None:
    """Resolve a built-in app skill directory by exact skill name.

    Uses a TTL cache to avoid repeated filesystem scans on hot paths.
    """
    skills_dir = base_dir or get_app_skills_dir()
    cache_key = str(skills_dir.resolve())

    cached = _app_skills_index_cache.get(cache_key)
    now = monotonic()
    if cached and now - cached[0] < _APP_SKILLS_CACHE_TTL_SECONDS:
        return cached[1].get(skill_name)

    index = _build_app_skills_index(skills_dir)
    _app_skills_index_cache[cache_key] = (now, index)
    return index.get(skill_name)


def render_skills_catalog(entries: list[SkillCatalogEntry]) -> str:
    """Render XML catalog text used in LLM system prompts."""
    if not entries:
        return ""

    lines = ["<available_skills>"]
    for entry in entries:
        lines.append("  <skill>")
        lines.append(f"    <name>{escape(entry.name)}</name>")
        lines.append(f"    <description>{escape(entry.description)}</description>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    lines.append(f"\n{SKILLS_CATALOG_FOOTER}")
    return "\n".join(lines)


def _resolve_skill_mcp_id(skill: object, repo_map: dict[str, object] | None = None) -> str | None:
    """Resolve the effective MCP config ID for a skill using an in-memory repo map.

    This is the synchronous helper used by build_skills_catalog() when repos are
    already loaded. For async single-skill lookups, use get_skill_effective_mcp_id().

    Args:
        skill: Skill document with mcp_config_id and git_repo_id attributes.
        repo_map: Pre-fetched repo_id -> SkillGitRepo mapping. If None, repo lookup is skipped.

    Returns:
        - The effective MCP config ID (str) if bound
        - ORPHANED_SKILL_SENTINEL if the skill references a deleted repo
        - None if no binding
    """
    # Skill-level binding takes precedence
    if skill.mcp_config_id:
        return str(skill.mcp_config_id)

    # Check repo-level binding
    if skill.git_repo_id:
        if repo_map is None:
            # No repo map provided, can't resolve repo binding
            return None
        repo = repo_map.get(str(skill.git_repo_id))
        if repo is None:
            # Orphaned skill: repo was deleted but skill still references it.
            # Return sentinel to hide skill from catalog (never matches any active MCP).
            # Log once per skill per process to avoid flooding logs on hot paths.
            skill_key = f"{getattr(skill, 'name', 'unknown')}:{skill.git_repo_id}"
            if skill_key not in _logged_orphaned_skills:
                _logged_orphaned_skills.add(skill_key)
                logger.warning(
                    "orphaned_skill_missing_repo",
                    skill_name=skill.name if hasattr(skill, "name") else "unknown",
                    git_repo_id=str(skill.git_repo_id),
                )
            return ORPHANED_SKILL_SENTINEL
        if repo.mcp_config_id:
            return str(repo.mcp_config_id)

    return None


async def build_skills_catalog(active_mcp_config_ids: list[str] | None = None) -> str:
    """Return an XML catalog of enabled skills for injection into LLM system prompts.

    Returns an empty string only when there are no enabled DB skills and no
    built-in app skills available (so callers can skip injection).
    """
    from beanie import PydanticObjectId

    from app.modules.llm.models import Skill, SkillGitRepo  # local import to avoid circular dep

    db_skills = await Skill.find(Skill.enabled == True).to_list()  # noqa: E712
    active_ids = {s for s in (active_mcp_config_ids or []) if s}

    repo_map: dict[str, SkillGitRepo] = {}
    repo_ids = {str(s.git_repo_id) for s in db_skills if s.git_repo_id}
    if repo_ids:
        repos = await SkillGitRepo.find({"_id": {"$in": [PydanticObjectId(r) for r in repo_ids]}}).to_list()
        repo_map = {str(repo.id): repo for repo in repos}

    entries: list[SkillCatalogEntry] = []
    for skill in db_skills:
        required_mcp_id = _resolve_skill_mcp_id(skill, repo_map)
        if required_mcp_id is None or required_mcp_id in active_ids:
            entries.append(SkillCatalogEntry(name=skill.name, description=skill.description))

    # Built-in app skills are always included, even if no DB skills are configured.
    # Use ALL enabled DB skill names for collision detection (not just included entries),
    # because activate_skill() finds DB skills first — if a DB skill exists but is filtered
    # out due to MCP binding, showing an app skill with the same name would be misleading.
    app_entries = load_app_skill_entries()
    reserved_names = {skill.name for skill in db_skills}
    for entry in app_entries:
        if entry.name in reserved_names:
            logger.info("app_skill_catalog_name_collision", name=entry.name)
            continue
        entries.append(entry)

    return render_skills_catalog(entries)


async def get_skill_effective_mcp_id(skill_name: str | None = None, *, skill: object | None = None) -> str | None:
    """Resolve the effective MCP config ID for a skill (skill-level binding takes precedence over repo-level).

    This is the async version that fetches repo from DB when needed. For batch
    operations with pre-loaded repos, use _resolve_skill_mcp_id() directly.

    Args:
        skill_name: Name of the skill to look up (ignored if skill is provided).
        skill: Pre-fetched Skill document to avoid duplicate DB query.

    Returns:
        The effective MCP config ID string when the skill is bound to an MCP config,
        ORPHANED_SKILL_SENTINEL when the skill references a deleted repo,
        or None if the skill has no binding or the skill doesn't exist.
    """
    from app.modules.llm.models import Skill, SkillGitRepo

    if skill is None:
        if not skill_name:
            return None
        skill = await Skill.find_one(Skill.name == skill_name, Skill.enabled == True)  # noqa: E712
        if not skill:
            return None

    # Quick path: skill-level binding (no DB lookup needed)
    if skill.mcp_config_id:
        return str(skill.mcp_config_id)

    # For repo-level binding, fetch the repo and use the shared helper
    if skill.git_repo_id:
        repo = await SkillGitRepo.get(skill.git_repo_id)
        repo_map = {str(skill.git_repo_id): repo} if repo else {}
        return _resolve_skill_mcp_id(skill, repo_map)

    return None


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

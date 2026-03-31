# AI Chat Skills Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Agent Skills support to all AI chat surfaces — admins load skills via SKILL.md paste or git repo, the LLM sees a catalog in every system prompt and calls `activate_skill` to load instructions on demand.

**Architecture:** `Skill` + `SkillGitRepo` Beanie documents track state; `skills_service.py` provides pure + async utilities (parse, scan, catalog builder); a new `activate_skill` FastMCP tool loads skill bodies; the catalog is injected into all LLM system prompts at the router level; Angular admin UI lives as a new component at the bottom of the LLM settings page.

**Tech Stack:** Python/FastAPI, Beanie/MongoDB, GitPython, FastMCP, Angular 21 + Material, TypeScript signals

---

## File Map

**Create:**
- `backend/app/modules/llm/services/skills_service.py` — parse_skill_md, scan_for_skills, list_skill_resources, build_skills_catalog, append_skills_to_messages, clone/pull helpers
- `backend/app/modules/mcp_server/tools/skills.py` — activate_skill MCP tool
- `backend/tests/unit/test_skills_service.py` — unit tests for pure functions in skills_service
- `frontend/src/app/features/admin/settings/llm/add-skill-dialog.component.ts` — dialog: paste SKILL.md
- `frontend/src/app/features/admin/settings/llm/add-repo-dialog.component.ts` — dialog: add git repo
- `frontend/src/app/features/admin/settings/llm/skills-admin.component.ts` — skills table + repo list

**Modify:**
- `backend/app/config.py` — add `skills_dir` field
- `backend/app/modules/llm/models.py` — add `Skill`, `SkillGitRepo` documents
- `backend/app/modules/__init__.py` — register new models in llm module
- `backend/app/modules/llm/schemas.py` — add skill/repo request+response schemas
- `backend/app/modules/llm/router.py` — add 7 endpoints + inject catalog into global_chat + summary endpoints
- `backend/app/modules/mcp_server/server.py` — import skills tool module
- `frontend/src/app/core/models/llm.model.ts` — add Skill, SkillGitRepo interfaces
- `frontend/src/app/core/services/llm.service.ts` — add 8 skill/repo methods
- `frontend/src/app/features/admin/settings/llm/settings-llm.component.ts` — add `<app-skills-admin>` section

---

### Task 1: Config + Data Models

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/modules/llm/models.py`
- Modify: `backend/app/modules/__init__.py`

- [ ] **Step 1: Add `skills_dir` to Settings**

  In `backend/app/config.py`, add after the `mist_oas_url` field (around line 85):

  ```python
  # Skills (Agent Skills filesystem storage)
  skills_dir: str = Field(default="/data/skills", description="Root directory for Agent Skills storage (must be a persistent volume in Docker)")
  ```

- [ ] **Step 2: Add `Skill` and `SkillGitRepo` documents to models.py**

  Add at the bottom of `backend/app/modules/llm/models.py`:

  ```python
  class SkillGitRepo(TimestampMixin, Document):
      """A git repository containing Agent Skills."""

      url: str = Field(..., description="Git repo URL (SSRF-validated on save)")
      branch: str = Field(default="main", description="Branch to clone/pull")
      token: str | None = Field(default=None, description="Encrypted deploy token")
      local_path: str = Field(..., description="Absolute path to clone destination")
      last_refreshed_at: datetime | None = Field(default=None, description="Last successful pull")
      error: str | None = Field(default=None, description="Last clone/pull error")

      class Settings:
          name = "skill_git_repos"
          indexes = ["url"]

      @property
      def token_set(self) -> bool:
          return self.token is not None


  class Skill(TimestampMixin, Document):
      """An Agent Skill loaded from SKILL.md."""

      name: str = Field(..., description="From SKILL.md frontmatter; unique")
      description: str = Field(..., description="From SKILL.md frontmatter")
      source: str = Field(..., description="'direct' or 'git'")
      local_path: str = Field(..., description="Absolute path to skill directory")
      enabled: bool = Field(default=True, description="Admin toggle")
      git_repo_id: PydanticObjectId | None = Field(default=None, description="FK to SkillGitRepo if source='git'")
      error: str | None = Field(default=None, description="Last parse/sync error")
      last_synced_at: datetime | None = Field(default=None, description="Last successful SKILL.md parse")

      class Settings:
          name = "skills"
          indexes = [
              IndexModel([("name", 1)], unique=True),
              "source",
              "enabled",
          ]
  ```

  Also add `IndexModel` to the imports at the top of `models.py`:
  ```python
  from pymongo import IndexModel
  ```
  (It's already imported — verify it's there, add if missing.)

- [ ] **Step 3: Register new models in module registry**

  In `backend/app/modules/__init__.py`, find the `llm` `AppModule` entry (around line 124) and add the two new models:

  ```python
  AppModule(
      name="llm",
      router_module="app.modules.llm.router",
      model_imports=[
          ("app.modules.llm.models", "LLMConfig"),
          ("app.modules.llm.models", "MCPConfig"),
          ("app.modules.llm.models", "LLMUsageLog"),
          ("app.modules.llm.models", "ConversationThread"),
          ("app.modules.llm.models", "Skill"),
          ("app.modules.llm.models", "SkillGitRepo"),
      ],
      tags=["LLM"],
  ),
  ```

- [ ] **Step 4: Start the backend and verify startup**

  ```bash
  cd backend && .venv/bin/python -m app.main
  ```

  Expected: server starts without import errors. MongoDB creates the `skills` and `skill_git_repos` collections automatically on first document insert.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/config.py backend/app/modules/llm/models.py backend/app/modules/__init__.py
  git commit -m "feat(skills): Skill + SkillGitRepo models + skills_dir config"
  ```

---

### Task 2: Skills Service Utilities

**Files:**
- Create: `backend/app/modules/llm/services/skills_service.py`
- Create: `backend/tests/unit/test_skills_service.py`

- [ ] **Step 1: Write the failing tests first**

  Create `backend/tests/unit/test_skills_service.py`:

  ```python
  """Unit tests for skills_service utility functions."""

  import pytest
  from pathlib import Path

  pytestmark = pytest.mark.unit


  # ── parse_skill_md ────────────────────────────────────────────────────────────

  class TestParseSkillMd:
      def test_parses_valid_skill(self, tmp_path):
          from app.modules.llm.services.skills_service import parse_skill_md
          f = tmp_path / "SKILL.md"
          f.write_text("---\nname: my-skill\ndescription: Does useful things.\n---\n\n# Body\nInstructions here.")
          name, desc, body = parse_skill_md(f)
          assert name == "my-skill"
          assert desc == "Does useful things."
          assert "Instructions here" in body

      def test_raises_on_missing_frontmatter(self, tmp_path):
          from app.modules.llm.services.skills_service import parse_skill_md
          f = tmp_path / "SKILL.md"
          f.write_text("# No frontmatter\nJust body.")
          with pytest.raises(ValueError, match="missing YAML frontmatter"):
              parse_skill_md(f)

      def test_raises_on_missing_description(self, tmp_path):
          from app.modules.llm.services.skills_service import parse_skill_md
          f = tmp_path / "SKILL.md"
          f.write_text("---\nname: my-skill\n---\n\nBody.")
          with pytest.raises(ValueError, match="description"):
              parse_skill_md(f)

      def test_lenient_unquoted_colon_in_description(self, tmp_path):
          from app.modules.llm.services.skills_service import parse_skill_md
          f = tmp_path / "SKILL.md"
          f.write_text("---\nname: my-skill\ndescription: Use when: user asks about PDFs\n---\n\nBody.")
          name, desc, body = parse_skill_md(f)
          assert "Use when" in desc

      def test_body_is_trimmed(self, tmp_path):
          from app.modules.llm.services.skills_service import parse_skill_md
          f = tmp_path / "SKILL.md"
          f.write_text("---\nname: s\ndescription: d\n---\n\n\n  Body line  \n\n")
          _, _, body = parse_skill_md(f)
          assert body == "Body line"


  # ── scan_for_skills ───────────────────────────────────────────────────────────

  class TestScanForSkills:
      def test_finds_skills_at_root(self, tmp_path):
          from app.modules.llm.services.skills_service import scan_for_skills
          (tmp_path / "skill-a").mkdir()
          (tmp_path / "skill-a" / "SKILL.md").write_text("---\nname: a\ndescription: d\n---")
          result = scan_for_skills(tmp_path)
          assert len(result) == 1
          assert result[0].name == "SKILL.md"

      def test_finds_skills_in_subdirectory(self, tmp_path):
          from app.modules.llm.services.skills_service import scan_for_skills
          nested = tmp_path / "skills" / "skill-b"
          nested.mkdir(parents=True)
          (nested / "SKILL.md").write_text("---\nname: b\ndescription: d\n---")
          result = scan_for_skills(tmp_path)
          assert len(result) == 1

      def test_skips_git_directory(self, tmp_path):
          from app.modules.llm.services.skills_service import scan_for_skills
          git_skill = tmp_path / ".git" / "skill-x"
          git_skill.mkdir(parents=True)
          (git_skill / "SKILL.md").write_text("---\nname: x\ndescription: d\n---")
          result = scan_for_skills(tmp_path)
          assert len(result) == 0

      def test_respects_max_depth(self, tmp_path):
          from app.modules.llm.services.skills_service import scan_for_skills
          deep = tmp_path
          for i in range(8):
              deep = deep / f"level{i}"
          deep.mkdir(parents=True)
          (deep / "SKILL.md").write_text("---\nname: deep\ndescription: d\n---")
          result = scan_for_skills(tmp_path, max_depth=6)
          assert len(result) == 0  # too deep, not found

      def test_returns_empty_for_nonexistent_dir(self, tmp_path):
          from app.modules.llm.services.skills_service import scan_for_skills
          result = scan_for_skills(tmp_path / "nonexistent")
          assert result == []


  # ── list_skill_resources ─────────────────────────────────────────────────────

  class TestListSkillResources:
      def test_lists_non_skill_files(self, tmp_path):
          from app.modules.llm.services.skills_service import list_skill_resources
          (tmp_path / "SKILL.md").write_text("---")
          (tmp_path / "script.py").write_text("print('hi')")
          (tmp_path / "data.json").write_text("{}")
          result = list_skill_resources(tmp_path)
          assert "script.py" in result
          assert "data.json" in result
          assert "SKILL.md" not in result

      def test_returns_empty_for_no_extra_files(self, tmp_path):
          from app.modules.llm.services.skills_service import list_skill_resources
          (tmp_path / "SKILL.md").write_text("---")
          result = list_skill_resources(tmp_path)
          assert result == []

      def test_returns_empty_for_nonexistent_dir(self, tmp_path):
          from app.modules.llm.services.skills_service import list_skill_resources
          result = list_skill_resources(tmp_path / "no-such-dir")
          assert result == []


  # ── append_skills_to_messages ─────────────────────────────────────────────────

  class TestAppendSkillsToMessages:
      def test_appends_catalog_to_system_message(self):
          from app.modules.llm.services.skills_service import append_skills_to_messages
          messages = [{"role": "system", "content": "Base prompt."}]
          result = append_skills_to_messages(messages, "<available_skills/>")
          assert "<available_skills/>" in result[0]["content"]

      def test_no_op_on_empty_catalog(self):
          from app.modules.llm.services.skills_service import append_skills_to_messages
          messages = [{"role": "system", "content": "Base."}]
          result = append_skills_to_messages(messages, "")
          assert result[0]["content"] == "Base."

      def test_no_op_on_empty_messages(self):
          from app.modules.llm.services.skills_service import append_skills_to_messages
          result = append_skills_to_messages([], "<catalog/>")
          assert result == []

      def test_no_op_if_first_message_not_system(self):
          from app.modules.llm.services.skills_service import append_skills_to_messages
          messages = [{"role": "user", "content": "Hello"}]
          result = append_skills_to_messages(messages, "<catalog/>")
          assert result[0]["content"] == "Hello"
  ```

- [ ] **Step 2: Run tests — expect ImportError (module not created yet)**

  ```bash
  cd backend && .venv/bin/pytest tests/unit/test_skills_service.py -v
  ```

  Expected: `ImportError: cannot import name 'parse_skill_md' from 'app.modules.llm.services.skills_service'`

- [ ] **Step 3: Create `skills_service.py`**

  Create `backend/app/modules/llm/services/skills_service.py`:

  ```python
  """
  Agent Skills utilities: filesystem scan, SKILL.md parsing, catalog builder, and git helpers.
  """

  import asyncio
  import re
  import shutil
  from datetime import datetime, timezone
  from pathlib import Path

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
      """Append a skills catalog string to the system message in a messages list.

      No-op if catalog is empty, messages list is empty, or first message is not 'system'.
      """
      if not catalog or not messages:
          return messages
      if messages[0].get("role") == "system":
          messages[0]["content"] += "\n\n" + catalog
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
          lines.append(f"    <name>{skill.name}</name>")
          lines.append(f"    <description>{skill.description}</description>")
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
      from urllib.parse import urlparse, urlunparse

      parsed = urlparse(url)
      netloc = f"oauth2:{token}@{parsed.hostname}"
      if parsed.port:
          netloc += f":{parsed.port}"
      return urlunparse(parsed._replace(netloc=netloc))


  async def clone_repo(url: str, token: str | None, branch: str, dest: Path) -> None:
      """Clone a git repository to dest (runs in a thread to avoid blocking the event loop)."""
      import git

      auth = _auth_url(url, token)

      def _clone() -> None:
          dest.mkdir(parents=True, exist_ok=True)
          git.Repo.clone_from(auth, str(dest), branch=branch, depth=1)

      await asyncio.to_thread(_clone)


  async def pull_repo(repo_path: Path, url: str, token: str | None) -> None:
      """Pull latest changes in an existing git clone (runs in a thread)."""
      import git

      auth = _auth_url(url, token)

      def _pull() -> None:
          repo = git.Repo(str(repo_path))
          origin = repo.remotes.origin
          origin.set_url(auth)
          origin.pull()

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
      from app.modules.llm.models import Skill
      from beanie import PydanticObjectId

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
              await skill.insert()
              added += 1

      return added, updated
  ```

- [ ] **Step 4: Run the tests — all should pass**

  ```bash
  cd backend && .venv/bin/pytest tests/unit/test_skills_service.py -v
  ```

  Expected: All tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/modules/llm/services/skills_service.py backend/tests/unit/test_skills_service.py
  git commit -m "feat(skills): skills_service utilities — parse, scan, catalog builder, git helpers"
  ```

---

### Task 3: API Schemas + Skill CRUD Endpoints

**Files:**
- Modify: `backend/app/modules/llm/schemas.py`
- Modify: `backend/app/modules/llm/router.py`

- [ ] **Step 1: Add skill schemas to schemas.py**

  Append to `backend/app/modules/llm/schemas.py`:

  ```python
  # ── Skills ───────────────────────────────────────────────────────────────────


  class AddDirectSkillRequest(BaseModel):
      """Add a skill from raw SKILL.md content."""
      content: str = Field(..., min_length=10, description="Raw SKILL.md text including YAML frontmatter")


  class SkillResponse(BaseModel):
      """A single skill record."""
      id: str
      name: str
      description: str
      source: str
      enabled: bool
      git_repo_id: str | None
      git_repo_url: str | None  # populated from joined repo document
      error: str | None
      last_synced_at: datetime | None


  class AddGitRepoRequest(BaseModel):
      """Add a git repository as a skills source."""
      url: str = Field(..., min_length=5, description="Git repo URL (HTTPS)")
      branch: str = Field(default="main", min_length=1)
      token: str | None = Field(default=None, description="Deploy token / PAT for private repos")


  class SkillGitRepoResponse(BaseModel):
      """A git repo skills source."""
      id: str
      url: str
      branch: str
      token_set: bool
      local_path: str
      last_refreshed_at: datetime | None
      error: str | None
  ```

- [ ] **Step 2: Add skill CRUD endpoints to router.py**

  In `backend/app/modules/llm/router.py`, add after the MCP config section (find the last `@router` decorator for MCP and add after it). Add a new section:

  ```python
  # ── Skills (Agent Skills support) ────────────────────────────────────────────


  def _skill_to_response(skill, git_repo_url: str | None = None) -> "SkillResponse":
      from app.modules.llm.schemas import SkillResponse
      return SkillResponse(
          id=str(skill.id),
          name=skill.name,
          description=skill.description,
          source=skill.source,
          enabled=skill.enabled,
          git_repo_id=str(skill.git_repo_id) if skill.git_repo_id else None,
          git_repo_url=git_repo_url,
          error=skill.error,
          last_synced_at=skill.last_synced_at,
      )


  def _repo_to_response(repo) -> "SkillGitRepoResponse":
      from app.modules.llm.schemas import SkillGitRepoResponse
      return SkillGitRepoResponse(
          id=str(repo.id),
          url=repo.url,
          branch=repo.branch,
          token_set=repo.token_set,
          local_path=repo.local_path,
          last_refreshed_at=repo.last_refreshed_at,
          error=repo.error,
      )


  @router.get("/llm/skills", tags=["LLM"])
  async def list_skills(
      _: User = Depends(require_admin),
  ):
      """List all skills. Admin only."""
      from app.modules.llm.models import Skill, SkillGitRepo

      skills = await Skill.find_all().to_list()
      # Build a repo URL lookup map to avoid N+1 queries
      repo_ids = {str(s.git_repo_id) for s in skills if s.git_repo_id}
      repos_by_id: dict[str, str] = {}
      if repo_ids:
          repos = await SkillGitRepo.find({"_id": {"$in": [PydanticObjectId(r) for r in repo_ids]}}).to_list()
          repos_by_id = {str(r.id): r.url for r in repos}

      return [_skill_to_response(s, repos_by_id.get(str(s.git_repo_id))) for s in skills]


  @router.post("/llm/skills/direct", status_code=status.HTTP_201_CREATED, tags=["LLM"])
  async def add_direct_skill(
      request: "AddDirectSkillRequest",
      _: User = Depends(require_admin),
  ):
      """Add a skill by pasting its SKILL.md content. Admin only."""
      from datetime import datetime, timezone
      from pathlib import Path

      from app.config import settings
      from app.modules.llm.models import Skill
      from app.modules.llm.schemas import AddDirectSkillRequest
      from app.modules.llm.services.skills_service import parse_skill_md

      req: AddDirectSkillRequest = request

      # Parse frontmatter from the submitted content
      import tempfile, os
      with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp:
          tmp.write(req.content)
          tmp_path = tmp.name

      try:
          try:
              name, description, _ = parse_skill_md(Path(tmp_path))
          except ValueError as exc:
              raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
      finally:
          os.unlink(tmp_path)

      if not name:
          raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKILL.md 'name' field is required")

      # Check for name collision
      existing = await Skill.find_one(Skill.name == name)
      if existing:
          raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"A skill named '{name}' already exists")

      # Write to filesystem
      skill_dir = Path(settings.skills_dir) / "direct" / name
      skill_dir.mkdir(parents=True, exist_ok=True)
      (skill_dir / "SKILL.md").write_text(req.content, encoding="utf-8")

      now = datetime.now(timezone.utc)
      skill = Skill(
          name=name,
          description=description,
          source="direct",
          local_path=str(skill_dir),
          enabled=True,
          error=None,
          last_synced_at=now,
      )
      await skill.insert()
      return _skill_to_response(skill)


  @router.patch("/llm/skills/{skill_id}/toggle", tags=["LLM"])
  async def toggle_skill(
      skill_id: str,
      _: User = Depends(require_admin),
  ):
      """Enable or disable a skill. Admin only."""
      from app.modules.llm.models import Skill

      oid = _parse_oid(skill_id, "skill ID")
      skill = await Skill.get(oid)
      if not skill:
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")

      skill.enabled = not skill.enabled
      await skill.save()
      return _skill_to_response(skill)


  @router.delete("/llm/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["LLM"])
  async def delete_skill(
      skill_id: str,
      _: User = Depends(require_admin),
  ):
      """Delete a direct-source skill (and its directory). Git-sourced skills cannot be deleted individually. Admin only."""
      from pathlib import Path

      from app.modules.llm.models import Skill
      from app.modules.llm.services.skills_service import remove_dir

      oid = _parse_oid(skill_id, "skill ID")
      skill = await Skill.get(oid)
      if not skill:
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
      if skill.source == "git":
          raise HTTPException(
              status_code=status.HTTP_400_BAD_REQUEST,
              detail="Git-sourced skills cannot be deleted individually. Disable the skill or delete the repo.",
          )

      remove_dir(Path(skill.local_path))
      await skill.delete()
  ```

  In `backend/app/modules/llm/router.py`, add the new schemas to the existing top-level import block (around line 19, inside the `from app.modules.llm.schemas import (...)` block):

  ```python
  from app.modules.llm.schemas import (
      # ... existing schemas ...
      AddDirectSkillRequest,
      AddGitRepoRequest,
      SkillGitRepoResponse,
      SkillResponse,
  )
  ```

- [ ] **Step 3: Run backend and spot-check with curl**

  ```bash
  cd backend && .venv/bin/python -m app.main
  ```

  In another terminal (replace TOKEN with a valid admin JWT):
  ```bash
  TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"email":"admin@example.com","password":"YourPassword"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

  curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/llm/skills
  ```

  Expected: `[]` (empty list).

  ```bash
  curl -s -X POST http://localhost:8000/api/v1/llm/skills/direct \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' \
    -d '{"content":"---\nname: test-skill\ndescription: A test skill.\n---\n\n# Test\nInstructions."}'
  ```

  Expected: `{"id": "...", "name": "test-skill", ...}`

- [ ] **Step 4: Commit**

  ```bash
  git add backend/app/modules/llm/schemas.py backend/app/modules/llm/router.py
  git commit -m "feat(skills): skill CRUD endpoints — list, add-direct, toggle, delete"
  ```

---

### Task 4: Git Repo Endpoints

**Files:**
- Modify: `backend/app/modules/llm/router.py`

- [ ] **Step 1: Add git repo endpoints**

  In `backend/app/modules/llm/router.py`, append the git repo section right after the skills CRUD block:

  ```python
  # ── Skill Git Repos ───────────────────────────────────────────────────────────


  @router.get("/llm/skills/repos", tags=["LLM"])
  async def list_skill_repos(
      _: User = Depends(require_admin),
  ):
      """List all git repo skills sources. Admin only."""
      from app.modules.llm.models import SkillGitRepo

      repos = await SkillGitRepo.find_all().to_list()
      return [_repo_to_response(r) for r in repos]


  @router.get("/llm/skills/repos/{repo_id}", tags=["LLM"])
  async def get_skill_repo(
      repo_id: str,
      _: User = Depends(require_admin),
  ):
      """Get a single git repo record (used for polling status). Admin only."""
      from app.modules.llm.models import SkillGitRepo

      oid = _parse_oid(repo_id, "repo ID")
      repo = await SkillGitRepo.get(oid)
      if not repo:
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")
      return _repo_to_response(repo)


  async def _clone_and_scan(repo_id: str) -> None:
      """Background task: clone a git repo and scan for skills."""
      from datetime import datetime, timezone
      from pathlib import Path

      from app.core.security import decrypt_sensitive_data
      from app.modules.llm.models import SkillGitRepo
      from app.modules.llm.services.skills_service import clone_repo, sync_skills_from_repo
      from beanie import PydanticObjectId

      repo = await SkillGitRepo.get(PydanticObjectId(repo_id))
      if not repo:
          return

      token = decrypt_sensitive_data(repo.token) if repo.token else None

      try:
          await clone_repo(repo.url, token, repo.branch, Path(repo.local_path))
          added, updated = await sync_skills_from_repo(repo_id, Path(repo.local_path))
          repo.last_refreshed_at = datetime.now(timezone.utc)
          repo.error = None
          await repo.save()
          logger.info("skill_repo_cloned", repo_id=repo_id, added=added, updated=updated)
      except Exception as exc:
          repo.error = str(exc)[:500]
          await repo.save()
          logger.error("skill_repo_clone_failed", repo_id=repo_id, error=str(exc))


  async def _pull_and_scan(repo_id: str) -> None:
      """Background task: pull a git repo and re-scan for skills."""
      from datetime import datetime, timezone
      from pathlib import Path

      from app.core.security import decrypt_sensitive_data
      from app.modules.llm.models import SkillGitRepo
      from app.modules.llm.services.skills_service import pull_repo, sync_skills_from_repo
      from beanie import PydanticObjectId

      repo = await SkillGitRepo.get(PydanticObjectId(repo_id))
      if not repo:
          return

      token = decrypt_sensitive_data(repo.token) if repo.token else None

      try:
          await pull_repo(Path(repo.local_path), repo.url, token)
          added, updated = await sync_skills_from_repo(repo_id, Path(repo.local_path))
          repo.last_refreshed_at = datetime.now(timezone.utc)
          repo.error = None
          await repo.save()
          logger.info("skill_repo_pulled", repo_id=repo_id, added=added, updated=updated)
      except Exception as exc:
          repo.error = str(exc)[:500]
          await repo.save()
          logger.error("skill_repo_pull_failed", repo_id=repo_id, error=str(exc))


  @router.post("/llm/skills/repos", status_code=status.HTTP_201_CREATED, tags=["LLM"])
  async def add_skill_repo(
      request: "AddGitRepoRequest",
      _: User = Depends(require_admin),
  ):
      """Add a git repo as a skills source. Clone + scan runs in the background. Admin only."""
      from datetime import datetime, timezone
      from pathlib import Path

      from app.config import settings
      from app.core.security import encrypt_sensitive_data
      from app.core.tasks import create_background_task
      from app.modules.llm.models import SkillGitRepo
      from app.modules.llm.schemas import AddGitRepoRequest
      from app.utils.url_safety import validate_outbound_url

      req: AddGitRepoRequest = request

      try:
          validate_outbound_url(req.url)
      except Exception as exc:
          raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid URL: {exc}") from exc

      encrypted_token = encrypt_sensitive_data(req.token) if req.token else None

      # Derive a local directory path using a placeholder ID first, then update
      repo = SkillGitRepo(
          url=req.url,
          branch=req.branch,
          token=encrypted_token,
          local_path="",  # will be set after insert (need the ID for the path)
      )
      await repo.insert()

      local_path = str(Path(settings.skills_dir) / "repos" / str(repo.id))
      repo.local_path = local_path
      await repo.save()

      create_background_task(_clone_and_scan(str(repo.id)), name=f"clone_skill_repo_{repo.id}")
      return _repo_to_response(repo)


  @router.post("/llm/skills/repos/{repo_id}/refresh", status_code=status.HTTP_202_ACCEPTED, tags=["LLM"])
  async def refresh_skill_repo(
      repo_id: str,
      _: User = Depends(require_admin),
  ):
      """Pull latest changes and re-scan for skills. Runs in the background. Admin only."""
      from app.core.tasks import create_background_task
      from app.modules.llm.models import SkillGitRepo

      oid = _parse_oid(repo_id, "repo ID")
      repo = await SkillGitRepo.get(oid)
      if not repo:
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

      create_background_task(_pull_and_scan(repo_id), name=f"pull_skill_repo_{repo_id}")
      return {"status": "refreshing"}


  @router.delete("/llm/skills/repos/{repo_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["LLM"])
  async def delete_skill_repo(
      repo_id: str,
      _: User = Depends(require_admin),
  ):
      """Delete a git repo, all its skills, and the cloned directory. Admin only."""
      from pathlib import Path

      from app.modules.llm.models import Skill, SkillGitRepo
      from app.modules.llm.services.skills_service import remove_dir

      oid = _parse_oid(repo_id, "repo ID")
      repo = await SkillGitRepo.get(oid)
      if not repo:
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repo not found")

      # Delete all skills from this repo
      await Skill.find(Skill.git_repo_id == oid).delete()

      # Remove cloned directory
      remove_dir(Path(repo.local_path))

      await repo.delete()
  ```

- [ ] **Step 2: Start the backend and verify endpoints appear in Swagger**

  Visit http://localhost:8000/api/v1/docs and confirm the new endpoints are listed under LLM:
  - `GET /llm/skills/repos`
  - `GET /llm/skills/repos/{repo_id}`
  - `POST /llm/skills/repos`
  - `POST /llm/skills/repos/{repo_id}/refresh`
  - `DELETE /llm/skills/repos/{repo_id}`

- [ ] **Step 3: Commit**

  ```bash
  git add backend/app/modules/llm/router.py
  git commit -m "feat(skills): git repo endpoints — add, get, refresh, delete"
  ```

---

### Task 5: `activate_skill` MCP Tool

**Files:**
- Create: `backend/app/modules/mcp_server/tools/skills.py`
- Modify: `backend/app/modules/mcp_server/server.py`

- [ ] **Step 1: Create the MCP tool module**

  Create `backend/app/modules/mcp_server/tools/skills.py`:

  ```python
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
  ```

- [ ] **Step 2: Register the tool in server.py**

  In `backend/app/modules/mcp_server/server.py`, add `skills` to the tools import line:

  ```python
  from app.modules.mcp_server.tools import backup, details, impact_analysis, search, skills, workflow  # noqa: E402, F401
  ```

- [ ] **Step 3: Start the backend and verify the tool is registered**

  ```bash
  cd backend && .venv/bin/python -m app.main
  ```

  Then use the MCP tool introspection endpoint (or check Swagger for `/mcp`). The tool `activate_skill` should appear in the tool list.

  Quick check via the in-process MCP client (paste into a Python shell with the app running):
  ```bash
  cd backend && .venv/bin/python -c "
  import asyncio
  from app.modules.llm.services.mcp_client import create_local_mcp_client
  async def main():
      client = create_local_mcp_client()
      tools = await client.list_tools()
      names = [t.name for t in tools]
      print('activate_skill' in names, names)
  asyncio.run(main())
  "
  ```

  Expected: `True ['search', 'backup', 'workflow', 'details', 'impact_analysis', 'activate_skill']`

- [ ] **Step 4: Commit**

  ```bash
  git add backend/app/modules/mcp_server/tools/skills.py backend/app/modules/mcp_server/server.py
  git commit -m "feat(skills): activate_skill MCP tool"
  ```

---

### Task 6: System Prompt Catalog Injection

**Files:**
- Modify: `backend/app/modules/llm/router.py`

The catalog must be injected into the `global_chat` endpoint at both places where the system prompt is constructed (new thread creation and existing-thread page-context update). All other summary endpoints use `append_skills_to_messages` on their messages list.

- [ ] **Step 1: Inject catalog into `global_chat` endpoint**

  In `backend/app/modules/llm/router.py`, find the `global_chat` function (around line 1440). Locate the imports section inside the function:

  ```python
  from app.modules.llm.services.prompt_builders import (
      _sanitize_for_prompt,
      build_global_chat_system_prompt,
      build_workflow_editor_context,
  )
  ```

  Add the catalog import and call right after the existing imports and before the system_prompt is used. Replace the `system_prompt = build_global_chat_system_prompt(...)` line and the second `base_prompt = build_global_chat_system_prompt(...)` occurrence:

  ```python
  from app.modules.llm.services.prompt_builders import (
      _sanitize_for_prompt,
      build_global_chat_system_prompt,
      build_workflow_editor_context,
  )
  from app.modules.llm.services.skills_service import build_skills_catalog

  llm = await create_llm_service()
  skills_catalog = await build_skills_catalog()
  system_prompt = build_global_chat_system_prompt(current_user.roles)
  if skills_catalog:
      system_prompt += "\n\n" + skills_catalog
  ```

  And the second usage (existing thread, page_context update, around line 1471):
  ```python
  base_prompt = build_global_chat_system_prompt(current_user.roles)
  if skills_catalog:
      base_prompt += "\n\n" + skills_catalog
  thread.messages[0].content = base_prompt + f"\n\nCurrent UI context:\n{safe_ctx}"
  ```

  Note: `skills_catalog` is already computed at the top of the function, so no duplicate DB call.

- [ ] **Step 2: Inject catalog into summary endpoints**

  For each summary endpoint that builds a `messages` list (backup, dashboard, audit-logs, system-logs, backups), find where the messages list is built and add the catalog injection. Pattern to follow:

  In each summary endpoint function, add after the messages list is built:
  ```python
  from app.modules.llm.services.skills_service import append_skills_to_messages, build_skills_catalog
  catalog = await build_skills_catalog()
  messages = append_skills_to_messages(messages, catalog)
  ```

  Locate these functions in router.py by searching for `build_backup_summary_prompt`, `build_dashboard_summary_prompt`, `build_audit_log_summary_prompt`, `build_system_log_summary_prompt`, `build_backup_list_summary_prompt`. Add the two-line injection in each.

- [ ] **Step 3: Write a test for catalog injection in global_chat path**

  Append to `backend/tests/unit/test_skills_service.py`:

  ```python
  class TestBuildSkillsCatalogIntegration:
      """Tests for catalog injection (pure helpers only — no DB)."""

      def test_append_skills_to_messages_full_catalog(self):
          from app.modules.llm.services.skills_service import append_skills_to_messages
          catalog = "<available_skills>\n  <skill><name>foo</name></skill>\n</available_skills>"
          messages = [
              {"role": "system", "content": "Base prompt."},
              {"role": "user", "content": "Hello"},
          ]
          result = append_skills_to_messages(messages, catalog)
          assert "<available_skills>" in result[0]["content"]
          assert result[1]["content"] == "Hello"  # user message untouched
  ```

- [ ] **Step 4: Run the test**

  ```bash
  cd backend && .venv/bin/pytest tests/unit/test_skills_service.py -v
  ```

  Expected: All tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/modules/llm/router.py backend/tests/unit/test_skills_service.py
  git commit -m "feat(skills): inject skills catalog into all LLM system prompts"
  ```

---

### Task 7: Frontend Models + Service Methods

**Files:**
- Modify: `frontend/src/app/core/models/llm.model.ts`
- Modify: `frontend/src/app/core/services/llm.service.ts`

- [ ] **Step 1: Add Skill and SkillGitRepo interfaces to llm.model.ts**

  Append to `frontend/src/app/core/models/llm.model.ts`:

  ```typescript
  export interface Skill {
    id: string;
    name: string;
    description: string;
    source: 'direct' | 'git';
    enabled: boolean;
    git_repo_id: string | null;
    git_repo_url: string | null;
    error: string | null;
    last_synced_at: string | null;
  }

  export interface SkillGitRepo {
    id: string;
    url: string;
    branch: string;
    token_set: boolean;
    local_path: string;
    last_refreshed_at: string | null;
    error: string | null;
  }
  ```

- [ ] **Step 2: Add skill/repo methods to llm.service.ts**

  In `frontend/src/app/core/services/llm.service.ts`, add the imports at the top:
  ```typescript
  import {
    // ... existing imports ...
    Skill,
    SkillGitRepo,
  } from '../models/llm.model';
  ```

  Then add these methods to the `LlmService` class:

  ```typescript
  // ── Skills ──────────────────────────────────────────────────────────────────

  listSkills(): Observable<Skill[]> {
    return this.api.get<Skill[]>('/llm/skills');
  }

  addDirectSkill(content: string): Observable<Skill> {
    return this.api.post<Skill>('/llm/skills/direct', { content });
  }

  toggleSkill(id: string): Observable<Skill> {
    return this.api.patch<Skill>(`/llm/skills/${id}/toggle`, {});
  }

  deleteSkill(id: string): Observable<void> {
    return this.api.delete<void>(`/llm/skills/${id}`);
  }

  listSkillRepos(): Observable<SkillGitRepo[]> {
    return this.api.get<SkillGitRepo[]>('/llm/skills/repos');
  }

  getSkillRepo(id: string): Observable<SkillGitRepo> {
    return this.api.get<SkillGitRepo>(`/llm/skills/repos/${id}`);
  }

  addSkillRepo(url: string, branch: string, token: string | null): Observable<SkillGitRepo> {
    return this.api.post<SkillGitRepo>('/llm/skills/repos', { url, branch, token });
  }

  refreshSkillRepo(id: string): Observable<{ status: string }> {
    return this.api.post<{ status: string }>(`/llm/skills/repos/${id}/refresh`, {});
  }

  deleteSkillRepo(id: string): Observable<void> {
    return this.api.delete<void>(`/llm/skills/repos/${id}`);
  }
  ```

- [ ] **Step 3: Check that LlmService compiles**

  ```bash
  cd frontend && npx ng build --configuration development 2>&1 | head -30
  ```

  Expected: No TypeScript errors related to the new methods.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/app/core/models/llm.model.ts frontend/src/app/core/services/llm.service.ts
  git commit -m "feat(skills): Angular Skill/SkillGitRepo models + LlmService skill methods"
  ```

---

### Task 8: Skills Admin Component + Dialogs

**Files:**
- Create: `frontend/src/app/features/admin/settings/llm/add-skill-dialog.component.ts`
- Create: `frontend/src/app/features/admin/settings/llm/add-repo-dialog.component.ts`
- Create: `frontend/src/app/features/admin/settings/llm/skills-admin.component.ts`

- [ ] **Step 1: Create add-skill-dialog.component.ts**

  Create `frontend/src/app/features/admin/settings/llm/add-skill-dialog.component.ts`:

  ```typescript
  import { Component, inject } from '@angular/core';
  import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
  import { MatButtonModule } from '@angular/material/button';
  import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
  import { MatFormFieldModule } from '@angular/material/form-field';
  import { MatInputModule } from '@angular/material/input';
  import { MatProgressBarModule } from '@angular/material/progress-bar';
  import { signal } from '@angular/core';
  import { LlmService } from '../../../../core/services/llm.service';
  import { extractErrorMessage } from '../../../../shared/utils/error.utils';

  @Component({
    selector: 'app-add-skill-dialog',
    standalone: true,
    imports: [
      ReactiveFormsModule,
      MatButtonModule,
      MatDialogModule,
      MatFormFieldModule,
      MatInputModule,
      MatProgressBarModule,
    ],
    template: `
      <h2 mat-dialog-title>Add Skill</h2>
      @if (saving()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }
      <mat-dialog-content>
        <p class="hint">Paste the full contents of a <code>SKILL.md</code> file below.</p>
        <mat-form-field appearance="outline" class="full-width">
          <mat-label>SKILL.md content</mat-label>
          <textarea
            matInput
            [formControl]="contentCtrl"
            rows="14"
            placeholder="---&#10;name: my-skill&#10;description: Does useful things.&#10;---&#10;&#10;# My Skill&#10;Instructions here."
          ></textarea>
          @if (contentCtrl.hasError('required')) {
            <mat-error>Content is required</mat-error>
          }
        </mat-form-field>
        @if (error()) {
          <p class="api-error">{{ error() }}</p>
        }
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button mat-dialog-close [disabled]="saving()">Cancel</button>
        <button mat-flat-button (click)="save()" [disabled]="saving() || contentCtrl.invalid">Add Skill</button>
      </mat-dialog-actions>
    `,
    styles: [
      `
        .full-width { width: 100%; }
        .hint { font-size: 13px; color: var(--mat-sys-on-surface-variant); margin-bottom: 12px; }
        .api-error { color: var(--app-error, #f44336); font-size: 13px; margin-top: 8px; }
        mat-dialog-content { min-width: 480px; }
      `,
    ],
  })
  export class AddSkillDialogComponent {
    private readonly llmService = inject(LlmService);
    private readonly dialogRef = inject(MatDialogRef<AddSkillDialogComponent>);

    contentCtrl = new FormControl('', [Validators.required, Validators.minLength(10)]);
    saving = signal(false);
    error = signal<string | null>(null);

    save(): void {
      if (this.contentCtrl.invalid || !this.contentCtrl.value) return;
      this.saving.set(true);
      this.error.set(null);
      this.llmService.addDirectSkill(this.contentCtrl.value).subscribe({
        next: () => this.dialogRef.close(true),
        error: (err) => {
          this.error.set(extractErrorMessage(err));
          this.saving.set(false);
        },
      });
    }
  }
  ```

- [ ] **Step 2: Create add-repo-dialog.component.ts**

  Create `frontend/src/app/features/admin/settings/llm/add-repo-dialog.component.ts`:

  ```typescript
  import { Component, inject, signal } from '@angular/core';
  import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
  import { MatButtonModule } from '@angular/material/button';
  import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
  import { MatFormFieldModule } from '@angular/material/form-field';
  import { MatInputModule } from '@angular/material/input';
  import { MatProgressBarModule } from '@angular/material/progress-bar';
  import { LlmService } from '../../../../core/services/llm.service';
  import { extractErrorMessage } from '../../../../shared/utils/error.utils';

  @Component({
    selector: 'app-add-repo-dialog',
    standalone: true,
    imports: [
      ReactiveFormsModule,
      MatButtonModule,
      MatDialogModule,
      MatFormFieldModule,
      MatInputModule,
      MatProgressBarModule,
    ],
    template: `
      <h2 mat-dialog-title>Add Git Repository</h2>
      @if (saving()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      }
      <mat-dialog-content>
        <p class="hint">
          Provide a git repo URL. The system will clone it and auto-discover all
          <code>SKILL.md</code> files. Clone runs in the background.
        </p>
        <form [formGroup]="form" class="form-grid">
          <mat-form-field appearance="outline" class="full-width">
            <mat-label>Repository URL</mat-label>
            <input matInput formControlName="url" placeholder="https://github.com/user/skills-repo.git" />
            @if (form.get('url')?.hasError('required')) {
              <mat-error>URL is required</mat-error>
            }
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Branch</mat-label>
            <input matInput formControlName="branch" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Access Token (optional)</mat-label>
            <input matInput formControlName="token" type="password" placeholder="ghp_... (for private repos)" />
          </mat-form-field>
        </form>
        @if (error()) {
          <p class="api-error">{{ error() }}</p>
        }
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button mat-dialog-close [disabled]="saving()">Cancel</button>
        <button mat-flat-button (click)="save()" [disabled]="saving() || form.invalid">Add Repository</button>
      </mat-dialog-actions>
    `,
    styles: [
      `
        .full-width { width: 100%; }
        .form-grid { display: flex; flex-direction: column; gap: 4px; }
        .hint { font-size: 13px; color: var(--mat-sys-on-surface-variant); margin-bottom: 12px; }
        .api-error { color: var(--app-error, #f44336); font-size: 13px; margin-top: 8px; }
        mat-dialog-content { min-width: 480px; }
      `,
    ],
  })
  export class AddRepoDialogComponent {
    private readonly llmService = inject(LlmService);
    private readonly dialogRef = inject(MatDialogRef<AddRepoDialogComponent>);
    private readonly fb = inject(FormBuilder);

    form = this.fb.group({
      url: ['', [Validators.required, Validators.minLength(5)]],
      branch: ['main', Validators.required],
      token: [''],
    });

    saving = signal(false);
    error = signal<string | null>(null);

    save(): void {
      if (this.form.invalid) return;
      const { url, branch, token } = this.form.value;
      this.saving.set(true);
      this.error.set(null);
      this.llmService.addSkillRepo(url!, branch!, token || null).subscribe({
        next: (repo) => this.dialogRef.close(repo),
        error: (err) => {
          this.error.set(extractErrorMessage(err));
          this.saving.set(false);
        },
      });
    }
  }
  ```

- [ ] **Step 3: Create skills-admin.component.ts**

  Create `frontend/src/app/features/admin/settings/llm/skills-admin.component.ts`:

  ```typescript
  import { DatePipe, SlicePipe } from '@angular/common';
  import { Component, inject, OnInit, signal } from '@angular/core';
  import { MatButtonModule } from '@angular/material/button';
  import { MatCardModule } from '@angular/material/card';
  import { MatDialog, MatDialogModule } from '@angular/material/dialog';
  import { MatIconModule } from '@angular/material/icon';
  import { MatProgressBarModule } from '@angular/material/progress-bar';
  import { MatSlideToggleModule } from '@angular/material/slide-toggle';
  import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
  import { MatTableModule } from '@angular/material/table';
  import { MatTooltipModule } from '@angular/material/tooltip';
  import { interval, Subscription } from 'rxjs';
  import { take, takeWhile } from 'rxjs/operators';
  import { ConfirmDialogComponent } from '../../../../shared/components/confirm-dialog/confirm-dialog.component';
  import { LlmService } from '../../../../core/services/llm.service';
  import { Skill, SkillGitRepo } from '../../../../core/models/llm.model';
  import { extractErrorMessage } from '../../../../shared/utils/error.utils';
  import { AddSkillDialogComponent } from './add-skill-dialog.component';
  import { AddRepoDialogComponent } from './add-repo-dialog.component';

  @Component({
    selector: 'app-skills-admin',
    standalone: true,
    imports: [
      DatePipe,
      SlicePipe,
      MatButtonModule,
      MatCardModule,
      MatDialogModule,
      MatIconModule,
      MatProgressBarModule,
      MatSlideToggleModule,
      MatSnackBarModule,
      MatTableModule,
      MatTooltipModule,
    ],
    template: `
      @if (loading()) {
        <mat-progress-bar mode="indeterminate"></mat-progress-bar>
      } @else {
        <!-- Git repos card -->
        <mat-card>
          <mat-card-header>
            <mat-card-title>Skills — Git Repositories</mat-card-title>
            <button mat-flat-button (click)="addRepo()">
              <mat-icon>add</mat-icon> Add Git Repo
            </button>
          </mat-card-header>
          <mat-card-content>
            @if (repos().length === 0) {
              <p class="empty-hint">No git repos configured. Add one to auto-discover skills.</p>
            } @else {
              <table mat-table [dataSource]="repos()" class="repo-table">
                <ng-container matColumnDef="url">
                  <th mat-header-cell *matHeaderCellDef>Repository</th>
                  <td mat-cell *matCellDef="let r">
                    <span class="repo-url">{{ r.url }}</span>
                    <span class="branch-badge">{{ r.branch }}</span>
                  </td>
                </ng-container>
                <ng-container matColumnDef="status">
                  <th mat-header-cell *matHeaderCellDef>Last Synced</th>
                  <td mat-cell *matCellDef="let r">
                    @if (syncingRepos().has(r.id)) {
                      <span class="syncing">Syncing…</span>
                    } @else if (r.error) {
                      <span class="error-text" [matTooltip]="r.error">
                        <mat-icon class="error-icon">error_outline</mat-icon> Error
                      </span>
                    } @else if (r.last_refreshed_at) {
                      {{ r.last_refreshed_at | date: 'short' }}
                    } @else {
                      <span class="pending">Pending…</span>
                    }
                  </td>
                </ng-container>
                <ng-container matColumnDef="actions">
                  <th mat-header-cell *matHeaderCellDef></th>
                  <td mat-cell *matCellDef="let r">
                    <div class="inline-actions">
                      <button
                        mat-icon-button
                        matTooltip="Refresh"
                        [disabled]="syncingRepos().has(r.id)"
                        (click)="refreshRepo(r)"
                      >
                        <mat-icon>sync</mat-icon>
                      </button>
                      <button mat-icon-button matTooltip="Delete" (click)="deleteRepo(r)">
                        <mat-icon>delete</mat-icon>
                      </button>
                    </div>
                  </td>
                </ng-container>
                <tr mat-header-row *matHeaderRowDef="repoColumns"></tr>
                <tr mat-row *matRowDef="let row; columns: repoColumns"></tr>
              </table>
            }
          </mat-card-content>
        </mat-card>

        <!-- Skills table card -->
        <mat-card>
          <mat-card-header>
            <mat-card-title>Skills</mat-card-title>
            <button mat-flat-button (click)="addSkill()">
              <mat-icon>add</mat-icon> Add Skill
            </button>
          </mat-card-header>
          <mat-card-content>
            @if (skills().length === 0) {
              <p class="empty-hint">No skills loaded yet. Add a SKILL.md directly or via a git repo.</p>
            } @else {
              <table mat-table [dataSource]="skills()" class="skills-table">
                <ng-container matColumnDef="name">
                  <th mat-header-cell *matHeaderCellDef>Name</th>
                  <td mat-cell *matCellDef="let s" [class.disabled-row]="!s.enabled">
                    {{ s.name }}
                    @if (s.error) {
                      <mat-icon class="error-icon" [matTooltip]="s.error">error_outline</mat-icon>
                    }
                  </td>
                </ng-container>
                <ng-container matColumnDef="description">
                  <th mat-header-cell *matHeaderCellDef>Description</th>
                  <td mat-cell *matCellDef="let s" [class.disabled-row]="!s.enabled">
                    {{ s.description | slice: 0 : 100 }}{{ s.description.length > 100 ? '…' : '' }}
                  </td>
                </ng-container>
                <ng-container matColumnDef="source">
                  <th mat-header-cell *matHeaderCellDef>Source</th>
                  <td mat-cell *matCellDef="let s">
                    @if (s.source === 'direct') {
                      <span class="badge badge-direct">direct</span>
                    } @else {
                      <span class="badge badge-git" [matTooltip]="s.git_repo_url || ''">
                        git
                      </span>
                    }
                  </td>
                </ng-container>
                <ng-container matColumnDef="enabled">
                  <th mat-header-cell *matHeaderCellDef>Enabled</th>
                  <td mat-cell *matCellDef="let s">
                    <mat-slide-toggle
                      [checked]="s.enabled"
                      (change)="toggleSkill(s)"
                    ></mat-slide-toggle>
                  </td>
                </ng-container>
                <ng-container matColumnDef="synced">
                  <th mat-header-cell *matHeaderCellDef>Last Synced</th>
                  <td mat-cell *matCellDef="let s">
                    {{ s.last_synced_at ? (s.last_synced_at | date: 'short') : '—' }}
                  </td>
                </ng-container>
                <ng-container matColumnDef="actions">
                  <th mat-header-cell *matHeaderCellDef></th>
                  <td mat-cell *matCellDef="let s">
                    @if (s.source === 'direct') {
                      <button mat-icon-button matTooltip="Delete" (click)="deleteSkill(s)">
                        <mat-icon>delete</mat-icon>
                      </button>
                    }
                  </td>
                </ng-container>
                <tr mat-header-row *matHeaderRowDef="skillColumns"></tr>
                <tr mat-row *matRowDef="let row; columns: skillColumns"></tr>
              </table>
            }
          </mat-card-content>
        </mat-card>
      }
    `,
    styles: [
      `
        mat-card { margin-bottom: 16px; }
        mat-card-header { display: flex; justify-content: space-between; align-items: center; }
        .empty-hint { color: var(--mat-sys-on-surface-variant); font-size: 13px; padding: 16px; text-align: center; }
        .repo-table, .skills-table { width: 100%; background: transparent; }
        .repo-url { font-family: monospace; font-size: 12px; }
        .branch-badge {
          font-size: 11px; padding: 2px 6px; border-radius: 8px; margin-left: 8px;
          background: var(--mat-sys-surface-variant); color: var(--mat-sys-on-surface-variant);
        }
        .syncing, .pending { color: var(--app-neutral, #888); font-size: 12px; }
        .error-text { color: var(--app-error, #f44336); font-size: 12px; display: flex; align-items: center; gap: 4px; }
        .error-icon { font-size: 16px; width: 16px; height: 16px; color: var(--app-error, #f44336); }
        .disabled-row { opacity: 0.5; }
        .badge {
          font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px;
        }
        .badge-direct {
          background: var(--mat-sys-secondary-container); color: var(--mat-sys-on-secondary-container);
        }
        .badge-git {
          background: var(--mat-sys-tertiary-container); color: var(--mat-sys-on-tertiary-container);
        }
        .inline-actions { display: flex; justify-content: flex-end; }
      `,
    ],
  })
  export class SkillsAdminComponent implements OnInit {
    private readonly llmService = inject(LlmService);
    private readonly dialog = inject(MatDialog);
    private readonly snackBar = inject(MatSnackBar);

    loading = signal(true);
    skills = signal<Skill[]>([]);
    repos = signal<SkillGitRepo[]>([]);
    syncingRepos = signal<Set<string>>(new Set());

    skillColumns = ['name', 'description', 'source', 'enabled', 'synced', 'actions'];
    repoColumns = ['url', 'status', 'actions'];

    private pollSubs = new Map<string, Subscription>();

    ngOnInit(): void {
      this.load();
    }

    load(): void {
      this.loading.set(true);
      this.llmService.listSkillRepos().subscribe({
        next: (repos) => {
          this.repos.set(repos);
          this.llmService.listSkills().subscribe({
            next: (skills) => {
              this.skills.set(skills);
              this.loading.set(false);
            },
            error: () => this.loading.set(false),
          });
        },
        error: () => this.loading.set(false),
      });
    }

    addSkill(): void {
      const ref = this.dialog.open(AddSkillDialogComponent, { width: '560px' });
      ref.afterClosed().subscribe((result) => {
        if (result) {
          this.load();
          this.snackBar.open('Skill added', 'OK', { duration: 3000 });
        }
      });
    }

    toggleSkill(skill: Skill): void {
      this.llmService.toggleSkill(skill.id).subscribe({
        next: (updated) => {
          this.skills.update((list) => list.map((s) => (s.id === updated.id ? updated : s)));
        },
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
    }

    deleteSkill(skill: Skill): void {
      const ref = this.dialog.open(ConfirmDialogComponent, {
        data: { title: 'Delete Skill', message: `Delete skill '${skill.name}'? This cannot be undone.` },
      });
      ref.afterClosed().subscribe((confirmed) => {
        if (!confirmed) return;
        this.llmService.deleteSkill(skill.id).subscribe({
          next: () => {
            this.skills.update((list) => list.filter((s) => s.id !== skill.id));
            this.snackBar.open(`'${skill.name}' deleted`, 'OK', { duration: 3000 });
          },
          error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
        });
      });
    }

    addRepo(): void {
      const ref = this.dialog.open(AddRepoDialogComponent, { width: '560px' });
      ref.afterClosed().subscribe((repo: SkillGitRepo | undefined) => {
        if (repo) {
          this.repos.update((list) => [...list, repo]);
          this._startPolling(repo.id);
          this.snackBar.open('Repository added — cloning in background…', 'OK', { duration: 4000 });
        }
      });
    }

    refreshRepo(repo: SkillGitRepo): void {
      this.llmService.refreshSkillRepo(repo.id).subscribe({
        next: () => {
          this._startPolling(repo.id);
          this.snackBar.open('Refresh started…', 'OK', { duration: 3000 });
        },
        error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
      });
    }

    deleteRepo(repo: SkillGitRepo): void {
      const ref = this.dialog.open(ConfirmDialogComponent, {
        data: {
          title: 'Delete Repository',
          message: `Delete '${repo.url}'? All skills from this repo will also be removed.`,
        },
      });
      ref.afterClosed().subscribe((confirmed) => {
        if (!confirmed) return;
        this.llmService.deleteSkillRepo(repo.id).subscribe({
          next: () => {
            this.repos.update((list) => list.filter((r) => r.id !== repo.id));
            this.skills.update((list) => list.filter((s) => s.git_repo_id !== repo.id));
            this.snackBar.open('Repository deleted', 'OK', { duration: 3000 });
          },
          error: (err) => this.snackBar.open(extractErrorMessage(err), 'OK', { duration: 5000 }),
        });
      });
    }

    private _startPolling(repoId: string): void {
      this.syncingRepos.update((s) => new Set([...s, repoId]));
      this.pollSubs.get(repoId)?.unsubscribe();

      let attempts = 0;
      const MAX_ATTEMPTS = 20; // 20 × 3s = 60s max

      const sub = interval(3000)
        .pipe(
          take(MAX_ATTEMPTS),
          takeWhile(() => this.syncingRepos().has(repoId)),
        )
        .subscribe(() => {
          attempts++;
          this.llmService.getSkillRepo(repoId).subscribe({
            next: (updated) => {
              this.repos.update((list) => list.map((r) => (r.id === repoId ? updated : r)));
              if (updated.last_refreshed_at || updated.error || attempts >= MAX_ATTEMPTS) {
                this._stopPolling(repoId);
                if (updated.error) {
                  this.snackBar.open(`Sync error: ${updated.error}`, 'OK', { duration: 8000 });
                } else if (updated.last_refreshed_at) {
                  this.load(); // reload full skills list now that sync completed
                  this.snackBar.open('Repository synced', 'OK', { duration: 3000 });
                }
              }
            },
          });
        });

      this.pollSubs.set(repoId, sub);
    }

    private _stopPolling(repoId: string): void {
      this.syncingRepos.update((s) => {
        const next = new Set(s);
        next.delete(repoId);
        return next;
      });
      this.pollSubs.get(repoId)?.unsubscribe();
      this.pollSubs.delete(repoId);
    }
  }
  ```

- [ ] **Step 4: Run a build to check for compile errors**

  ```bash
  cd frontend && npx ng build --configuration development 2>&1 | grep -E "ERROR|error TS"
  ```

  Expected: No TypeScript errors.

- [ ] **Step 5: Commit**

  ```bash
  git add \
    frontend/src/app/features/admin/settings/llm/add-skill-dialog.component.ts \
    frontend/src/app/features/admin/settings/llm/add-repo-dialog.component.ts \
    frontend/src/app/features/admin/settings/llm/skills-admin.component.ts
  git commit -m "feat(skills): SkillsAdminComponent + Add Skill/Add Repo dialogs"
  ```

---

### Task 9: Wire Skills Admin into LLM Settings Page

**Files:**
- Modify: `frontend/src/app/features/admin/settings/llm/settings-llm.component.ts`

- [ ] **Step 1: Add SkillsAdminComponent to settings-llm.component.ts**

  In `frontend/src/app/features/admin/settings/llm/settings-llm.component.ts`:

  1. Add import at the top:
     ```typescript
     import { SkillsAdminComponent } from './skills-admin.component';
     ```

  2. Add `SkillsAdminComponent` to the `imports` array in `@Component`:
     ```typescript
     imports: [
       // ... existing imports ...
       SkillsAdminComponent,
     ],
     ```

  3. Add the `<app-skills-admin>` element at the end of the template, inside the `@if (llmEnabled())` block, after the existing MCP configs card (or after the LLM configs card if no MCP section exists). Add it right before the closing `</div>` of `<div class="tab-form wide">`:

     ```html
     @if (llmEnabled()) {
       <!-- ... existing LLM and MCP config cards ... -->

       <app-skills-admin></app-skills-admin>
     }
     ```

- [ ] **Step 2: Build and verify no errors**

  ```bash
  cd frontend && npx ng build --configuration development 2>&1 | grep -E "ERROR|error TS"
  ```

  Expected: No TypeScript errors.

- [ ] **Step 3: Start the full stack and do a manual end-to-end test**

  In separate terminals:
  ```bash
  # Terminal 1: backend
  cd backend && .venv/bin/python -m app.main

  # Terminal 2: frontend
  cd frontend && npm start
  ```

  1. Log in as admin
  2. Navigate to Admin → Settings → LLM
  3. Enable LLM Features if not already enabled
  4. Scroll to the Skills section
  5. Click "Add Skill" → paste a minimal SKILL.md → click "Add Skill" → skill appears in table
  6. Toggle the skill off and back on → enabled state updates
  7. Click "Add Git Repo" → enter a public repo URL (e.g. a test repo) → repo appears in syncing state → observe poll completing
  8. Verify skill catalog appears in the system prompt: open the global chat and send "what skills do you have?" — the LLM should respond listing the skill name

- [ ] **Step 4: Final commit**

  ```bash
  git add frontend/src/app/features/admin/settings/llm/settings-llm.component.ts
  git commit -m "feat(skills): wire SkillsAdminComponent into LLM settings page"
  ```

---

### Task 10: Update CLAUDE.md Files

**Files:**
- Modify: `backend/app/modules/llm/CLAUDE.md`
- Modify: `backend/app/modules/mcp_server/CLAUDE.md`

- [ ] **Step 1: Update LLM module CLAUDE.md**

  Add to `backend/app/modules/llm/CLAUDE.md` under the Backend section:

  ```
  - **Agent Skills**: `Skill` and `SkillGitRepo` Beanie documents in `models.py`. `services/skills_service.py` provides `parse_skill_md()`, `scan_for_skills()`, `list_skill_resources()`, `build_skills_catalog()`, `append_skills_to_messages()`, `clone_repo()`, `pull_repo()`. Skills are stored on a persistent filesystem (`SKILLS_DIR` env var, default `/data/skills`). Catalog injected into all LLM system prompts via `build_skills_catalog()` called in each router endpoint. Admin CRUD endpoints under `/llm/skills` and `/llm/skills/repos` (all require `require_admin`). Git repos cloned via background task; polling via `GET /llm/skills/repos/{id}`.
  ```

  Add to the Frontend section:
  ```
  - **Skills admin** (`features/admin/settings/llm/skills-admin.component.ts`): table of enabled/disabled skills + git repo management with background-sync polling. Dialogs: `add-skill-dialog` (paste SKILL.md), `add-repo-dialog` (git URL + branch + token). Mounted at bottom of LLM settings page inside `llmEnabled` guard.
  ```

- [ ] **Step 2: Update MCP server CLAUDE.md**

  Add to `backend/app/modules/mcp_server/CLAUDE.md`:

  ```
  - **`activate_skill` tool** (`tools/skills.py`): loads the full body of a named enabled `Skill` document from the filesystem. Returns content wrapped in `<skill_content name="...">` tags with `<skill_resources>` listing bundled files. Returns a graceful error string (not exception) if the skill is missing or the file is gone.
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add backend/app/modules/llm/CLAUDE.md backend/app/modules/mcp_server/CLAUDE.md
  git commit -m "docs: update CLAUDE.md for Agent Skills feature"
  ```

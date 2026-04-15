"""Unit tests for skills_service utility functions."""

import pytest

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
        _, desc, _ = parse_skill_md(f)
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


class TestAppSkillsHelpers:
    def test_load_app_skill_entries_reads_dedicated_folder(self, tmp_path):
        from app.modules.llm.services.skills_service import load_app_skill_entries

        skill_dir = tmp_path / "digital-twin"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: digital-twin\n"
            "description: Simulate config safely\n"
            "---\n\n"
            "# Body\n"
            "Use this for simulation.\n"
        )

        entries = load_app_skill_entries(tmp_path)

        assert len(entries) == 1
        assert entries[0].name == "digital-twin"
        assert entries[0].description == "Simulate config safely"

    def test_find_app_skill_dir_resolves_by_exact_name(self, tmp_path):
        from app.modules.llm.services.skills_service import find_app_skill_dir

        skill_dir = tmp_path / "impact-analysis"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: impact-analysis\n"
            "description: Analyze impact sessions\n"
            "---\n\n"
            "Body\n"
        )

        resolved = find_app_skill_dir("impact-analysis", tmp_path)
        missing = find_app_skill_dir("Impact-Analysis", tmp_path)

        assert resolved == skill_dir
        assert missing is None

    def test_render_skills_catalog_includes_instruction_footer(self):
        from app.modules.llm.services.skills_service import SkillCatalogEntry, render_skills_catalog

        catalog = render_skills_catalog(
            [
                SkillCatalogEntry(name="digital-twin", description="Simulate changes"),
                SkillCatalogEntry(name="impact-analysis", description="Analyze sessions"),
            ]
        )

        assert "<available_skills>" in catalog
        assert "<name>digital-twin</name>" in catalog
        assert "<name>impact-analysis</name>" in catalog
        assert "call the activate_skill tool" in catalog

    def test_get_app_skills_dir_uses_override_setting(self, monkeypatch):
        from pathlib import Path

        from app.config import settings
        from app.modules.llm.services.skills_service import get_app_skills_dir

        monkeypatch.setattr(settings, "app_skills_dir", "/tmp/custom-app-skills", raising=False)
        assert get_app_skills_dir() == Path("/tmp/custom-app-skills")


class TestBuildSkillsCatalog:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_db_or_app_skills(self, monkeypatch):
        import app.modules.llm.models as llm_models
        from app.modules.llm.services import skills_service

        class _Query:
            async def to_list(self):
                return []

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _Query()

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _Query()

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr(skills_service, "load_app_skill_entries", lambda *_args, **_kwargs: [])

        catalog = await skills_service.build_skills_catalog()

        assert catalog == ""

    @pytest.mark.asyncio
    async def test_merges_db_and_app_skills_and_dedups_by_name(self, monkeypatch):
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import SkillCatalogEntry, build_skills_catalog

        db_skills = [
            SimpleNamespace(name="shared", description="DB shared", git_repo_id=None, mcp_config_id=None),
            SimpleNamespace(name="db-only", description="DB only", git_repo_id=None, mcp_config_id=None),
        ]

        class _Query:
            def __init__(self, items):
                self._items = items

            async def to_list(self):
                return self._items

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _Query(db_skills)

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _Query([])

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *_args, **_kwargs: [
                SkillCatalogEntry(name="shared", description="APP shared"),
                SkillCatalogEntry(name="app-only", description="APP only"),
            ],
        )

        catalog = await build_skills_catalog()

        assert catalog.count("<name>shared</name>") == 1
        assert "<description>DB shared</description>" in catalog
        assert "<name>db-only</name>" in catalog
        assert "<name>app-only</name>" in catalog

    @pytest.mark.asyncio
    async def test_skill_with_direct_mcp_binding_included_when_active(self, monkeypatch):
        """Skill with skill-level mcp_config_id is included when the MCP ID is in active list."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import build_skills_catalog

        db_skills = [
            SimpleNamespace(name="bound-skill", description="Bound to MCP", git_repo_id=None, mcp_config_id="mcp-001"),
            SimpleNamespace(name="free-skill", description="No binding", git_repo_id=None, mcp_config_id=None),
        ]

        class _Query:
            def __init__(self, items):
                self._items = items

            async def to_list(self):
                return self._items

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _Query(db_skills)

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _Query([])

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr("app.modules.llm.services.skills_service.load_app_skill_entries", lambda *_args: [])

        # With MCP active
        catalog = await build_skills_catalog(["mcp-001"])

        assert "<name>bound-skill</name>" in catalog
        assert "<name>free-skill</name>" in catalog

    @pytest.mark.asyncio
    async def test_skill_with_direct_mcp_binding_excluded_when_not_active(self, monkeypatch):
        """Skill with skill-level mcp_config_id is excluded when the MCP ID is NOT in active list."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import build_skills_catalog

        db_skills = [
            SimpleNamespace(name="bound-skill", description="Bound to MCP", git_repo_id=None, mcp_config_id="mcp-001"),
            SimpleNamespace(name="free-skill", description="No binding", git_repo_id=None, mcp_config_id=None),
        ]

        class _Query:
            def __init__(self, items):
                self._items = items

            async def to_list(self):
                return self._items

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _Query(db_skills)

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _Query([])

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr("app.modules.llm.services.skills_service.load_app_skill_entries", lambda *_args: [])

        # Without MCP active (different ID)
        catalog = await build_skills_catalog(["mcp-999"])

        assert "<name>bound-skill</name>" not in catalog
        assert "<name>free-skill</name>" in catalog

    @pytest.mark.asyncio
    async def test_skill_with_repo_level_mcp_binding_included_when_active(self, monkeypatch):
        """Git-sourced skill inherits repo mcp_config_id and is included when MCP is active."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import build_skills_catalog

        repo_id = "aaaabbbbccccddddeeee0001"  # Valid 24-char hex ObjectId
        db_skills = [
            SimpleNamespace(
                name="git-skill", description="From repo", git_repo_id=repo_id, mcp_config_id=None
            ),
        ]
        repos = [
            SimpleNamespace(id=repo_id, mcp_config_id="mcp-from-repo"),
        ]

        class _SkillQuery:
            async def to_list(self):
                return db_skills

        class _RepoQuery:
            async def to_list(self):
                return repos

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _SkillQuery()

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _RepoQuery()

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr("app.modules.llm.services.skills_service.load_app_skill_entries", lambda *_args: [])

        # With repo MCP active
        catalog = await build_skills_catalog(["mcp-from-repo"])

        assert "<name>git-skill</name>" in catalog

    @pytest.mark.asyncio
    async def test_skill_with_repo_level_mcp_binding_excluded_when_not_active(self, monkeypatch):
        """Git-sourced skill inherits repo mcp_config_id and is excluded when MCP is not active."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import build_skills_catalog

        repo_id = "aaaabbbbccccddddeeee0002"  # Valid 24-char hex ObjectId
        db_skills = [
            SimpleNamespace(
                name="git-skill", description="From repo", git_repo_id=repo_id, mcp_config_id=None
            ),
        ]
        repos = [
            SimpleNamespace(id=repo_id, mcp_config_id="mcp-from-repo"),
        ]

        class _SkillQuery:
            async def to_list(self):
                return db_skills

        class _RepoQuery:
            async def to_list(self):
                return repos

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _SkillQuery()

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _RepoQuery()

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr("app.modules.llm.services.skills_service.load_app_skill_entries", lambda *_args: [])

        # Without repo MCP active
        catalog = await build_skills_catalog(["some-other-mcp"])

        assert "<name>git-skill</name>" not in catalog

    @pytest.mark.asyncio
    async def test_skill_level_binding_overrides_repo_level(self, monkeypatch):
        """When skill has its own mcp_config_id, it overrides the repo's binding."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import build_skills_catalog

        repo_id = "aaaabbbbccccddddeeee0003"  # Valid 24-char hex ObjectId
        db_skills = [
            SimpleNamespace(
                name="override-skill",
                description="Skill-level binding",
                git_repo_id=repo_id,
                mcp_config_id="skill-mcp",  # Skill-level binding
            ),
        ]
        repos = [
            SimpleNamespace(id=repo_id, mcp_config_id="repo-mcp"),  # Repo-level binding (should be ignored)
        ]

        class _SkillQuery:
            async def to_list(self):
                return db_skills

        class _RepoQuery:
            async def to_list(self):
                return repos

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _SkillQuery()

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _RepoQuery()

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr("app.modules.llm.services.skills_service.load_app_skill_entries", lambda *_args: [])

        # Skill's own MCP is active (not the repo's)
        catalog_with_skill_mcp = await build_skills_catalog(["skill-mcp"])
        catalog_with_repo_mcp = await build_skills_catalog(["repo-mcp"])

        assert "<name>override-skill</name>" in catalog_with_skill_mcp
        assert "<name>override-skill</name>" not in catalog_with_repo_mcp

    @pytest.mark.asyncio
    async def test_empty_or_none_active_ids_excludes_bound_skills(self, monkeypatch):
        """Skills with bindings are excluded when active_mcp_config_ids is None or empty."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import build_skills_catalog

        db_skills = [
            SimpleNamespace(name="bound", description="Bound", git_repo_id=None, mcp_config_id="mcp-001"),
            SimpleNamespace(name="unbound", description="Free", git_repo_id=None, mcp_config_id=None),
        ]

        class _Query:
            def __init__(self, items):
                self._items = items

            async def to_list(self):
                return self._items

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _Query(db_skills)

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _Query([])

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr("app.modules.llm.services.skills_service.load_app_skill_entries", lambda *_args: [])

        catalog_none = await build_skills_catalog(None)
        catalog_empty = await build_skills_catalog([])

        for catalog in [catalog_none, catalog_empty]:
            assert "<name>bound</name>" not in catalog
            assert "<name>unbound</name>" in catalog

    @pytest.mark.asyncio
    async def test_orphaned_skill_hidden_when_repo_missing(self, monkeypatch):
        """Skill referencing a deleted repo is hidden from catalog (treated as restricted)."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import build_skills_catalog

        missing_repo_id = "aaaabbbbccccddddeeee9999"
        db_skills = [
            SimpleNamespace(
                name="orphaned-skill",
                description="Orphaned",
                git_repo_id=missing_repo_id,  # References repo that doesn't exist
                mcp_config_id=None,
            ),
            SimpleNamespace(name="normal-skill", description="Normal", git_repo_id=None, mcp_config_id=None),
        ]

        class _SkillQuery:
            async def to_list(self):
                return db_skills

        class _RepoQuery:
            async def to_list(self):
                return []  # Repo doesn't exist

        class _FakeSkill:
            enabled = object()

            @staticmethod
            def find(*_args, **_kwargs):
                return _SkillQuery()

        class _FakeSkillRepo:
            @staticmethod
            def find(*_args, **_kwargs):
                return _RepoQuery()

        monkeypatch.setattr(llm_models, "Skill", _FakeSkill)
        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)
        monkeypatch.setattr("app.modules.llm.services.skills_service.load_app_skill_entries", lambda *_args: [])

        # Orphaned skill should be hidden even with all MCPs active
        catalog = await build_skills_catalog(["any-mcp-id"])

        assert "<name>orphaned-skill</name>" not in catalog
        assert "<name>normal-skill</name>" in catalog


class TestGetSkillEffectiveMcpId:
    @pytest.mark.asyncio
    async def test_returns_none_for_unbound_skill(self):
        """Skill without MCP binding returns None."""
        from types import SimpleNamespace

        from app.modules.llm.services.skills_service import get_skill_effective_mcp_id

        skill = SimpleNamespace(name="test", mcp_config_id=None, git_repo_id=None)

        result = await get_skill_effective_mcp_id(skill=skill)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_skill_level_binding(self):
        """Skill-level mcp_config_id is returned when set."""
        from types import SimpleNamespace

        from app.modules.llm.services.skills_service import get_skill_effective_mcp_id

        skill = SimpleNamespace(name="test", mcp_config_id="skill-mcp-123", git_repo_id=None)

        result = await get_skill_effective_mcp_id(skill=skill)

        assert result == "skill-mcp-123"

    @pytest.mark.asyncio
    async def test_returns_repo_level_binding(self, monkeypatch):
        """Repo-level mcp_config_id is returned when skill has none."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import get_skill_effective_mcp_id

        repo_id = "aaaabbbbccccddddeeee0001"
        skill = SimpleNamespace(name="test", mcp_config_id=None, git_repo_id=repo_id)
        repo = SimpleNamespace(id=repo_id, mcp_config_id="repo-mcp-456")

        class _FakeSkillRepo:
            @staticmethod
            async def get(_id):
                return repo

        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)

        result = await get_skill_effective_mcp_id(skill=skill)

        assert result == "repo-mcp-456"

    @pytest.mark.asyncio
    async def test_orphaned_skill_returns_sentinel(self, monkeypatch):
        """Skill referencing deleted repo returns sentinel (blocks activation)."""
        from types import SimpleNamespace

        import app.modules.llm.models as llm_models
        from app.modules.llm.services.skills_service import get_skill_effective_mcp_id

        skill = SimpleNamespace(name="orphan", mcp_config_id=None, git_repo_id="missing-repo-id")

        class _FakeSkillRepo:
            @staticmethod
            async def get(_id):
                return None  # Repo doesn't exist

        monkeypatch.setattr(llm_models, "SkillGitRepo", _FakeSkillRepo)

        result = await get_skill_effective_mcp_id(skill=skill)

        assert result == "<orphaned:repo_deleted>"

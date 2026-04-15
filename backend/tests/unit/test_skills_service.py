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


# ── build_skills_catalog filtering ────────────────────────────────────────────


class TestBuildSkillsCatalogFiltering:
    """Tests for MCP-based skill filtering in build_skills_catalog."""

    @pytest.fixture
    def mock_skills_setup(self):
        """Set up mock skill and repo objects with different MCP bindings."""
        from unittest.mock import MagicMock

        # Use valid ObjectId-style strings for IDs.
        REPO_1_ID = "507f1f77bcf86cd799439011"
        REPO_2_ID = "507f1f77bcf86cd799439012"
        MCP_1_ID = "507f1f77bcf86cd799439021"
        MCP_2_ID = "507f1f77bcf86cd799439022"

        # Create mock skill documents.
        def make_skill(name: str, desc: str, enabled: bool, mcp_config_id=None, git_repo_id=None):
            skill = MagicMock()
            skill.name = name
            skill.description = desc
            skill.enabled = enabled
            skill.mcp_config_id = mcp_config_id
            skill.git_repo_id = git_repo_id
            return skill

        def make_repo(repo_id: str, mcp_config_id=None):
            repo = MagicMock()
            repo.id = repo_id
            repo.mcp_config_id = mcp_config_id
            return repo

        # Skills with different MCP bindings:
        # - skill_unbound: no MCP binding (always visible)
        # - skill_direct_mcp: direct MCP binding to MCP_1_ID
        # - skill_git_mcp: git repo binding to MCP_2_ID (via repo)
        # - skill_git_unbound: git repo without MCP binding
        skill_unbound = make_skill("unbound-skill", "No MCP", True)
        skill_direct_mcp = make_skill("direct-mcp-skill", "Direct MCP binding", True, mcp_config_id=MCP_1_ID)
        skill_git_mcp = make_skill("git-mcp-skill", "Git repo with MCP", True, git_repo_id=REPO_1_ID)
        skill_git_unbound = make_skill("git-unbound-skill", "Git repo no MCP", True, git_repo_id=REPO_2_ID)

        repo_with_mcp = make_repo(REPO_1_ID, mcp_config_id=MCP_2_ID)
        repo_without_mcp = make_repo(REPO_2_ID, mcp_config_id=None)

        all_skills = [skill_unbound, skill_direct_mcp, skill_git_mcp, skill_git_unbound]
        all_repos = [repo_with_mcp, repo_without_mcp]

        return {
            "skills": all_skills,
            "repos": all_repos,
            "skill_unbound": skill_unbound,
            "skill_direct_mcp": skill_direct_mcp,
            "skill_git_mcp": skill_git_mcp,
            "skill_git_unbound": skill_git_unbound,
            "MCP_1_ID": MCP_1_ID,
            "MCP_2_ID": MCP_2_ID,
        }

    def _patch_db_calls(self, monkeypatch, skills, repos):
        """Patch Skill.find and SkillGitRepo.find to return mock data."""
        from unittest.mock import AsyncMock, MagicMock

        # Mock the entire Skill class find method chain.
        # The local import in build_skills_catalog uses app.modules.llm.models.
        skill_find_result = MagicMock()
        skill_find_result.to_list = AsyncMock(return_value=skills)

        # Mock Skill class - need 'enabled' attribute for the filter expression.
        skill_class_mock = MagicMock()
        skill_class_mock.enabled = True  # Makes Skill.enabled == True usable
        skill_class_mock.find = MagicMock(return_value=skill_find_result)
        monkeypatch.setattr("app.modules.llm.models.Skill", skill_class_mock)

        repo_find_result = MagicMock()
        repo_find_result.to_list = AsyncMock(return_value=repos)

        repo_class_mock = MagicMock()
        repo_class_mock.find = MagicMock(return_value=repo_find_result)
        monkeypatch.setattr("app.modules.llm.models.SkillGitRepo", repo_class_mock)

    @pytest.mark.asyncio
    async def test_no_mcp_filter_shows_only_unbound_skills(self, monkeypatch, mock_skills_setup):
        """When active_mcp_config_ids is None (no MCP servers active), only unbound skills are visible."""
        from app.modules.llm.services.skills_service import build_skills_catalog

        self._patch_db_calls(monkeypatch, mock_skills_setup["skills"], mock_skills_setup["repos"])
        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *a, **kw: [],
        )

        catalog = await build_skills_catalog(active_mcp_config_ids=None)

        # Only unbound skills should be in the catalog (same as empty list).
        assert "<name>unbound-skill</name>" in catalog
        assert "<name>git-unbound-skill</name>" in catalog
        # MCP-bound skills should NOT be in the catalog since no MCPs are active.
        assert "<name>direct-mcp-skill</name>" not in catalog
        assert "<name>git-mcp-skill</name>" not in catalog

    @pytest.mark.asyncio
    async def test_empty_mcp_filter_excludes_bound_skills(self, monkeypatch, mock_skills_setup):
        """When active_mcp_config_ids is empty list, only unbound skills are included."""
        from app.modules.llm.services.skills_service import build_skills_catalog

        self._patch_db_calls(monkeypatch, mock_skills_setup["skills"], mock_skills_setup["repos"])
        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *a, **kw: [],
        )

        catalog = await build_skills_catalog(active_mcp_config_ids=[])

        # Only unbound skills (no MCP binding) should be in the catalog.
        assert "<name>unbound-skill</name>" in catalog
        assert "<name>git-unbound-skill</name>" in catalog
        # MCP-bound skills should be excluded.
        assert "<name>direct-mcp-skill</name>" not in catalog
        assert "<name>git-mcp-skill</name>" not in catalog

    @pytest.mark.asyncio
    async def test_mcp_filter_includes_matching_direct_binding(self, monkeypatch, mock_skills_setup):
        """Skills with matching direct MCP binding are included."""
        from app.modules.llm.services.skills_service import build_skills_catalog

        self._patch_db_calls(monkeypatch, mock_skills_setup["skills"], mock_skills_setup["repos"])
        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *a, **kw: [],
        )

        catalog = await build_skills_catalog(active_mcp_config_ids=[mock_skills_setup["MCP_1_ID"]])

        # Unbound + direct-mcp (matches MCP_1_ID) should be in.
        assert "<name>unbound-skill</name>" in catalog
        assert "<name>direct-mcp-skill</name>" in catalog
        assert "<name>git-unbound-skill</name>" in catalog
        # git-mcp is bound to MCP_2_ID (not in active list), should be excluded.
        assert "<name>git-mcp-skill</name>" not in catalog

    @pytest.mark.asyncio
    async def test_mcp_filter_includes_matching_repo_binding(self, monkeypatch, mock_skills_setup):
        """Skills with matching repo-level MCP binding are included."""
        from app.modules.llm.services.skills_service import build_skills_catalog

        self._patch_db_calls(monkeypatch, mock_skills_setup["skills"], mock_skills_setup["repos"])
        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *a, **kw: [],
        )

        catalog = await build_skills_catalog(active_mcp_config_ids=[mock_skills_setup["MCP_2_ID"]])

        # Unbound + git-mcp (via repo with MCP_2_ID) should be in.
        assert "<name>unbound-skill</name>" in catalog
        assert "<name>git-mcp-skill</name>" in catalog
        assert "<name>git-unbound-skill</name>" in catalog
        # direct-mcp is bound to MCP_1_ID (not in active list), should be excluded.
        assert "<name>direct-mcp-skill</name>" not in catalog

    @pytest.mark.asyncio
    async def test_mcp_filter_with_multiple_active_servers(self, monkeypatch, mock_skills_setup):
        """Multiple active MCP servers include all matching skills."""
        from app.modules.llm.services.skills_service import build_skills_catalog

        self._patch_db_calls(monkeypatch, mock_skills_setup["skills"], mock_skills_setup["repos"])
        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *a, **kw: [],
        )

        catalog = await build_skills_catalog(
            active_mcp_config_ids=[mock_skills_setup["MCP_1_ID"], mock_skills_setup["MCP_2_ID"]]
        )

        # All skills should be included (MCP_1_ID covers direct, MCP_2_ID covers git repo).
        assert "<name>unbound-skill</name>" in catalog
        assert "<name>direct-mcp-skill</name>" in catalog
        assert "<name>git-mcp-skill</name>" in catalog
        assert "<name>git-unbound-skill</name>" in catalog

    @pytest.mark.asyncio
    async def test_app_skills_always_included_even_with_mcp_filter(self, monkeypatch, mock_skills_setup):
        """Built-in app skills are always included regardless of MCP filter."""
        from app.modules.llm.services.skills_service import SkillCatalogEntry, build_skills_catalog

        self._patch_db_calls(monkeypatch, mock_skills_setup["skills"], mock_skills_setup["repos"])
        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *a, **kw: [SkillCatalogEntry(name="digital-twin", description="Always available")],
        )

        catalog = await build_skills_catalog(active_mcp_config_ids=[])

        # App skill should always be in the catalog.
        assert "<name>digital-twin</name>" in catalog

    @pytest.mark.asyncio
    async def test_app_skill_name_collision_logs_and_skips(self, monkeypatch, mock_skills_setup, caplog):
        """When DB skill has same name as app skill, app skill is skipped with log."""
        from unittest.mock import AsyncMock, MagicMock

        from app.modules.llm.services.skills_service import SkillCatalogEntry, build_skills_catalog

        # Create a DB skill with the same name as an app skill.
        colliding_skill = MagicMock()
        colliding_skill.name = "digital-twin"
        colliding_skill.description = "DB version"
        colliding_skill.enabled = True
        colliding_skill.mcp_config_id = None
        colliding_skill.git_repo_id = None

        skill_find_result = MagicMock()
        skill_find_result.to_list = AsyncMock(return_value=[colliding_skill])

        skill_class_mock = MagicMock()
        skill_class_mock.enabled = True
        skill_class_mock.find = MagicMock(return_value=skill_find_result)
        monkeypatch.setattr("app.modules.llm.models.Skill", skill_class_mock)

        repo_find_result = MagicMock()
        repo_find_result.to_list = AsyncMock(return_value=[])

        repo_class_mock = MagicMock()
        repo_class_mock.find = MagicMock(return_value=repo_find_result)
        monkeypatch.setattr("app.modules.llm.models.SkillGitRepo", repo_class_mock)

        monkeypatch.setattr(
            "app.modules.llm.services.skills_service.load_app_skill_entries",
            lambda *a, **kw: [SkillCatalogEntry(name="digital-twin", description="App version")],
        )

        catalog = await build_skills_catalog(active_mcp_config_ids=None)

        # DB skill should be included (it was added first).
        assert "<name>digital-twin</name>" in catalog
        # Only one entry (not duplicated).
        assert catalog.count("<name>digital-twin</name>") == 1

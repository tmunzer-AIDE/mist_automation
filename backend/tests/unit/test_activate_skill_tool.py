"""Unit tests for activate_skill MCP tool access control."""

import pytest
from fastmcp.exceptions import ToolError

pytestmark = pytest.mark.unit


class TestActivateSkillMcpAccessControl:
    """Tests for MCP binding enforcement in activate_skill tool."""

    @pytest.mark.asyncio
    async def test_skill_with_mcp_binding_blocked_without_active_mcp(self, monkeypatch, tmp_path):
        """Skill bound to MCP is blocked when that MCP is not active in the thread."""
        from types import SimpleNamespace

        from app.modules.mcp_server import server as mcp_server
        from app.modules.mcp_server.tools.skills import activate_skill

        # Create a valid SKILL.md file
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test-skill\ndescription: Test\n---\n\nBody")

        skill = SimpleNamespace(
            name="test-skill",
            enabled=True,
            local_path=str(skill_dir),
            mcp_config_id="required-mcp-123",
            git_repo_id=None,
        )

        class _FakeSkill:
            enabled = True
            name = "test-skill"

            @staticmethod
            async def find_one(*_args, **_kwargs):
                return skill

        monkeypatch.setattr("app.modules.llm.models.Skill", _FakeSkill)
        # No thread context set (mcp_thread_id_var.get() returns None) - external client scenario
        monkeypatch.setattr(mcp_server, "mcp_thread_id_var", SimpleNamespace(get=lambda: None))

        with pytest.raises(ToolError, match="External MCP clients.*cannot activate MCP-bound skills"):
            await activate_skill(name="test-skill")

    @pytest.mark.asyncio
    async def test_skill_with_mcp_binding_allowed_when_mcp_active(self, monkeypatch, tmp_path):
        """Skill bound to MCP is allowed when that MCP is active in the thread."""
        from types import SimpleNamespace

        from app.modules.mcp_server.server import mcp_thread_id_var
        from app.modules.mcp_server.tools.skills import activate_skill

        # Create a valid SKILL.md file
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test-skill\ndescription: Test\n---\n\nBody content")

        skill = SimpleNamespace(
            name="test-skill",
            enabled=True,
            local_path=str(skill_dir),
            mcp_config_id="required-mcp-123",
            git_repo_id=None,
        )

        thread = SimpleNamespace(
            mcp_config_ids=["required-mcp-123", "other-mcp"],
        )

        class _FakeSkill:
            enabled = True
            name = "test-skill"

            @staticmethod
            async def find_one(*_args, **_kwargs):
                return skill

        class _FakeThread:
            @staticmethod
            async def get(_id):
                return thread

        # Patch at the module level so inline imports pick it up
        monkeypatch.setattr("app.modules.llm.models.Skill", _FakeSkill)
        monkeypatch.setattr("app.modules.llm.models.ConversationThread", _FakeThread)
        # Set the ContextVar with a valid 24-char ObjectId hex string
        token = mcp_thread_id_var.set("aaaabbbbccccddddeeee1234")
        try:
            result = await activate_skill(name="test-skill")
        finally:
            mcp_thread_id_var.reset(token)

        assert '<skill_content name="test-skill">' in result
        assert "Body content" in result

    @pytest.mark.asyncio
    async def test_skill_with_repo_mcp_binding_blocked_without_active_mcp(self, monkeypatch, tmp_path):
        """Skill inheriting MCP binding from repo is blocked when that MCP is not active."""
        from types import SimpleNamespace

        from app.modules.mcp_server.server import mcp_thread_id_var
        from app.modules.mcp_server.tools.skills import activate_skill

        skill_dir = tmp_path / "git-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: git-skill\ndescription: Git skill\n---\n\nBody")

        repo_id = "aaaabbbbccccddddeeee0001"
        skill = SimpleNamespace(
            name="git-skill",
            enabled=True,
            local_path=str(skill_dir),
            mcp_config_id=None,  # No skill-level binding
            git_repo_id=repo_id,
        )
        repo = SimpleNamespace(
            id=repo_id,
            mcp_config_id="repo-mcp-456",  # Repo-level binding
        )

        thread = SimpleNamespace(
            mcp_config_ids=["different-mcp"],  # Repo's MCP not in list
        )

        class _FakeSkill:
            enabled = True
            name = "git-skill"

            @staticmethod
            async def find_one(*_args, **_kwargs):
                return skill

        class _FakeSkillGitRepo:
            @staticmethod
            async def get(_id):
                return repo

        class _FakeThread:
            @staticmethod
            async def get(_id):
                return thread

        monkeypatch.setattr("app.modules.llm.models.Skill", _FakeSkill)
        monkeypatch.setattr("app.modules.llm.models.SkillGitRepo", _FakeSkillGitRepo)
        monkeypatch.setattr("app.modules.llm.models.ConversationThread", _FakeThread)
        token = mcp_thread_id_var.set("aaaabbbbccccddddeeee1234")
        try:
            with pytest.raises(ToolError, match="requires MCP server that is not enabled"):
                await activate_skill(name="git-skill")
        finally:
            mcp_thread_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_unbound_skill_always_activatable(self, monkeypatch, tmp_path):
        """Skill without any MCP binding is always activatable."""
        from types import SimpleNamespace

        from app.modules.mcp_server.tools.skills import activate_skill

        skill_dir = tmp_path / "free-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: free-skill\ndescription: Free\n---\n\nFree body")

        skill = SimpleNamespace(
            name="free-skill",
            enabled=True,
            local_path=str(skill_dir),
            mcp_config_id=None,
            git_repo_id=None,
        )

        class _FakeSkill:
            enabled = True
            name = "free-skill"

            @staticmethod
            async def find_one(*_args, **_kwargs):
                return skill

        monkeypatch.setattr("app.modules.llm.models.Skill", _FakeSkill)
        # No thread context needed - unbound skill doesn't check MCP

        result = await activate_skill(name="free-skill")

        assert '<skill_content name="free-skill">' in result

    @pytest.mark.asyncio
    async def test_orphaned_skill_blocked(self, monkeypatch, tmp_path):
        """Skill with orphaned repo reference is blocked from activation."""
        from types import SimpleNamespace

        from app.modules.mcp_server.tools.skills import activate_skill

        skill_dir = tmp_path / "orphan-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: orphan-skill\ndescription: Orphan\n---\n\nBody")

        skill = SimpleNamespace(
            name="orphan-skill",
            enabled=True,
            local_path=str(skill_dir),
            mcp_config_id=None,
            git_repo_id="deleted-repo-id",  # References non-existent repo
        )

        class _FakeSkill:
            enabled = True
            name = "orphan-skill"

            @staticmethod
            async def find_one(*_args, **_kwargs):
                return skill

        class _FakeSkillGitRepo:
            @staticmethod
            async def get(_id):
                return None  # Repo deleted

        monkeypatch.setattr("app.modules.llm.models.Skill", _FakeSkill)
        monkeypatch.setattr("app.modules.llm.models.SkillGitRepo", _FakeSkillGitRepo)
        # No thread context - orphaned skill gets explicit error about deleted repo

        with pytest.raises(ToolError, match="git repository it was imported from has been deleted"):
            await activate_skill(name="orphan-skill")

    @pytest.mark.asyncio
    async def test_app_skill_fallback_always_works(self, monkeypatch, tmp_path):
        """Built-in app skills are always activatable (no MCP binding)."""
        import app.modules.llm.services.skills_service as skills_service
        from app.modules.mcp_server.tools.skills import activate_skill

        # Create app skill directory
        app_skill_dir = tmp_path / "app-skill"
        app_skill_dir.mkdir()
        (app_skill_dir / "SKILL.md").write_text("---\nname: app-skill\ndescription: App\n---\n\nApp body")

        class _FakeSkill:
            enabled = True
            name = "app-skill"

            @staticmethod
            async def find_one(*_args, **_kwargs):
                return None  # Not in DB

        monkeypatch.setattr("app.modules.llm.models.Skill", _FakeSkill)
        monkeypatch.setattr(skills_service, "find_app_skill_dir", lambda name: app_skill_dir if name == "app-skill" else None)

        result = await activate_skill(name="app-skill")

        assert '<skill_content name="app-skill">' in result
        assert "App body" in result

    @pytest.mark.asyncio
    async def test_disabled_skill_not_found(self, monkeypatch):
        """Disabled skill raises not found error."""
        import app.modules.llm.services.skills_service as skills_service
        from app.modules.mcp_server.tools.skills import activate_skill

        class _FakeSkill:
            enabled = True
            name = "disabled-skill"

            @staticmethod
            async def find_one(*_args, **_kwargs):
                return None  # Skill.enabled == True query excludes disabled

        monkeypatch.setattr("app.modules.llm.models.Skill", _FakeSkill)
        monkeypatch.setattr(skills_service, "find_app_skill_dir", lambda name: None)

        with pytest.raises(ToolError, match="not found or not enabled"):
            await activate_skill(name="disabled-skill")

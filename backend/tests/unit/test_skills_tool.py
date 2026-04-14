"""Unit tests for MCP activate_skill access-control behavior."""

from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

# Import server first to prime tool registration and avoid circular-import issues.
from app.modules.mcp_server import server  # noqa: F401
from app.modules.mcp_server.tools import skills as skills_tool

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_is_skill_allowed_in_current_chat_when_unbound(monkeypatch):
    async def _resolve_none(_skill):
        return None

    monkeypatch.setattr(skills_tool, "_resolve_required_mcp_config_id", _resolve_none)

    assert await skills_tool._is_skill_allowed_in_current_chat(object()) is True


@pytest.mark.asyncio
async def test_is_skill_allowed_in_current_chat_requires_thread_for_bound_skill(monkeypatch):
    async def _resolve_required(_skill):
        return "mcp-required"

    monkeypatch.setattr(skills_tool, "_resolve_required_mcp_config_id", _resolve_required)

    token = skills_tool.mcp_thread_id_var.set(None)
    try:
        assert await skills_tool._is_skill_allowed_in_current_chat(object()) is False
    finally:
        skills_tool.mcp_thread_id_var.reset(token)


@pytest.mark.asyncio
async def test_is_skill_allowed_in_current_chat_matches_thread_mcp_ids(monkeypatch):
    from app.modules.llm.models import ConversationThread

    async def _resolve_required(_skill):
        return "mcp-required"

    async def _fake_get(_oid):
        return SimpleNamespace(mcp_config_ids=["mcp-required", "other-mcp"])

    monkeypatch.setattr(skills_tool, "_resolve_required_mcp_config_id", _resolve_required)
    monkeypatch.setattr(ConversationThread, "get", _fake_get)

    token = skills_tool.mcp_thread_id_var.set("507f1f77bcf86cd799439011")
    try:
        assert await skills_tool._is_skill_allowed_in_current_chat(object()) is True
    finally:
        skills_tool.mcp_thread_id_var.reset(token)


@pytest.mark.asyncio
async def test_is_skill_allowed_in_current_chat_rejects_non_matching_mcp(monkeypatch):
    from app.modules.llm.models import ConversationThread

    async def _resolve_required(_skill):
        return "mcp-required"

    async def _fake_get(_oid):
        return SimpleNamespace(mcp_config_ids=["different-mcp"])

    monkeypatch.setattr(skills_tool, "_resolve_required_mcp_config_id", _resolve_required)
    monkeypatch.setattr(ConversationThread, "get", _fake_get)

    token = skills_tool.mcp_thread_id_var.set("507f1f77bcf86cd799439011")
    try:
        assert await skills_tool._is_skill_allowed_in_current_chat(object()) is False
    finally:
        skills_tool.mcp_thread_id_var.reset(token)


@pytest.mark.asyncio
async def test_activate_skill_rejects_skill_not_allowed_in_chat_context(monkeypatch, tmp_path):
    import app.modules.llm.models as llm_models

    skill_dir = tmp_path / "restricted-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: restricted-skill\n"
        "description: Restricted skill\n"
        "---\n\n"
        "Run restricted flow\n",
        encoding="utf-8",
    )

    fake_skill = SimpleNamespace(local_path=str(skill_dir), mcp_config_id=None, git_repo_id=None)

    class _QueryField:
        def __eq__(self, _other):
            return True

    class _FakeSkillModel:
        name = _QueryField()
        enabled = _QueryField()

        @staticmethod
        async def find_one(*_args, **_kwargs):
            return fake_skill

    async def _deny(_skill):
        return False

    monkeypatch.setattr(llm_models, "Skill", _FakeSkillModel)
    monkeypatch.setattr(skills_tool, "_is_skill_allowed_in_current_chat", _deny)

    with pytest.raises(ToolError, match="not available in this chat context"):
        await skills_tool.activate_skill("restricted-skill")


@pytest.mark.asyncio
async def test_activate_skill_returns_content_when_allowed(monkeypatch, tmp_path):
    import app.modules.llm.models as llm_models

    skill_dir = tmp_path / "allowed-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: allowed-skill\n"
        "description: Allowed skill\n"
        "---\n\n"
        "Do the allowed thing\n",
        encoding="utf-8",
    )

    fake_skill = SimpleNamespace(local_path=str(skill_dir), mcp_config_id=None, git_repo_id=None)

    class _QueryField:
        def __eq__(self, _other):
            return True

    class _FakeSkillModel:
        name = _QueryField()
        enabled = _QueryField()

        @staticmethod
        async def find_one(*_args, **_kwargs):
            return fake_skill

    async def _allow(_skill):
        return True

    monkeypatch.setattr(llm_models, "Skill", _FakeSkillModel)
    monkeypatch.setattr(skills_tool, "_is_skill_allowed_in_current_chat", _allow)

    result = await skills_tool.activate_skill("allowed-skill")

    assert "<skill_content" in result
    assert "allowed-skill" in result
    assert "Do the allowed thing" in result

"""Regression tests for global chat history and error handling."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_global_chat_stores_sanitized_error_metadata(client, monkeypatch, test_user):
    import app.api.v1.llm as llm_api
    import app.models.system as system_models
    import app.modules.llm.services.agent_service as agent_service
    import app.modules.llm.services.llm_service_factory as llm_factory
    import app.modules.llm.services.prompt_builders as prompt_builders
    import app.modules.llm.services.skills_service as skills_service
    from app.modules.llm.models import ConversationThread

    async def _fake_create_llm_service():
        return object()

    async def _fake_build_skills_catalog(_mcp_ids):
        return ""

    async def _fake_get_canvas_instructions() -> str:
        return ""

    async def _fake_load_external_mcp_clients(_config_ids):
        return []

    async def _fake_get_config(_cls):
        return SimpleNamespace(memory_enabled=False, maintenance_mode=False)

    @asynccontextmanager
    async def _fake_mcp_user_session(*_args, **_kwargs):
        yield []

    async def _fake_run(self, *args, **kwargs):
        raise RuntimeError("sensitive token leak")

    monkeypatch.setattr(llm_factory, "create_llm_service", _fake_create_llm_service)
    monkeypatch.setattr(skills_service, "build_skills_catalog", _fake_build_skills_catalog)
    monkeypatch.setattr(llm_api, "_get_canvas_instructions", _fake_get_canvas_instructions)
    monkeypatch.setattr(llm_api, "_load_external_mcp_clients", _fake_load_external_mcp_clients)
    monkeypatch.setattr(llm_api, "_mcp_user_session", _fake_mcp_user_session)
    monkeypatch.setattr(prompt_builders, "build_global_chat_system_prompt", lambda *_args, **_kwargs: "prompt-v1")
    monkeypatch.setattr(system_models.SystemConfig, "get_config", classmethod(_fake_get_config))
    monkeypatch.setattr(agent_service.AIAgentService, "run", _fake_run)

    resp = await client.post("/api/v1/llm/chat", json={"message": "hello"})
    assert resp.status_code == 500

    rows = (
        await ConversationThread.find(
            ConversationThread.user_id == test_user.id,
            ConversationThread.feature == "global_chat",
        )
        .sort("-updated_at")
        .to_list(1)
    )
    assert rows
    thread = rows[0]
    assert thread.messages[-1].role == "assistant"
    assert thread.messages[-1].metadata == {"error": "RuntimeError"}
    assert "sensitive token leak" not in str(thread.messages[-1].metadata)


@pytest.mark.asyncio
async def test_global_chat_refreshes_system_prompt_each_turn(client, monkeypatch, test_user):
    import app.api.v1.llm as llm_api
    import app.models.system as system_models
    import app.modules.llm.services.agent_service as agent_service
    import app.modules.llm.services.llm_service_factory as llm_factory
    import app.modules.llm.services.prompt_builders as prompt_builders
    import app.modules.llm.services.skills_service as skills_service
    from app.modules.llm.models import ConversationThread
    from app.modules.llm.services.agent_service import AgentResult

    existing = ConversationThread(user_id=test_user.id, feature="global_chat")
    existing.add_message("system", "stale-system-prompt")
    existing.add_message("user", "old user")
    existing.add_message("assistant", "old assistant")
    await existing.insert()

    captured: dict = {}

    async def _fake_create_llm_service():
        return object()

    async def _fake_build_skills_catalog(_mcp_ids):
        return ""

    async def _fake_get_canvas_instructions() -> str:
        return ""

    async def _fake_load_external_mcp_clients(_config_ids):
        return []

    async def _fake_get_config(_cls):
        return SimpleNamespace(memory_enabled=False, maintenance_mode=False)

    async def _fake_maybe_trigger_compaction(_thread):
        return None

    @asynccontextmanager
    async def _fake_mcp_user_session(*_args, **_kwargs):
        yield []

    async def _fake_run(self, *args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        return AgentResult(status="completed", result="ok", tool_calls=[], iterations=1)

    monkeypatch.setattr(llm_factory, "create_llm_service", _fake_create_llm_service)
    monkeypatch.setattr(skills_service, "build_skills_catalog", _fake_build_skills_catalog)
    monkeypatch.setattr(llm_api, "_get_canvas_instructions", _fake_get_canvas_instructions)
    monkeypatch.setattr(llm_api, "_load_external_mcp_clients", _fake_load_external_mcp_clients)
    monkeypatch.setattr(llm_api, "_mcp_user_session", _fake_mcp_user_session)
    monkeypatch.setattr(llm_api, "_maybe_trigger_compaction", _fake_maybe_trigger_compaction)
    monkeypatch.setattr(prompt_builders, "build_global_chat_system_prompt", lambda *_args, **_kwargs: "fresh-system-prompt")
    monkeypatch.setattr(system_models.SystemConfig, "get_config", classmethod(_fake_get_config))
    monkeypatch.setattr(agent_service.AIAgentService, "run", _fake_run)

    resp = await client.post(
        "/api/v1/llm/chat",
        json={"thread_id": str(existing.id), "message": "next turn"},
    )

    assert resp.status_code == 200

    updated = await ConversationThread.get(existing.id)
    assert updated is not None
    assert updated.messages[0].role == "system"
    assert updated.messages[0].content == "fresh-system-prompt"

    sent_messages = captured["messages"]
    assert sent_messages is not None
    assert sent_messages[0].role == "system"
    assert sent_messages[0].content == "fresh-system-prompt"
    assert [m.role for m in sent_messages] == ["system", "user", "assistant"]

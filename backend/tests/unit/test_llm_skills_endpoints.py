"""Regression tests for LLM skills endpoints and summary catalog wiring."""

from datetime import datetime, timezone

from beanie import PydanticObjectId


class TestToggleSkillEndpoint:
    async def test_toggle_git_skill_returns_repo_derived_fields(self, client, test_db):
        """PATCH /llm/skills/{id}/toggle should not crash for git skills and should include repo metadata."""
        from app.modules.llm.models import Skill, SkillGitRepo

        repo = SkillGitRepo(
            url="https://example.com/skills.git",
            branch="main",
            token=None,
            mcp_config_id=PydanticObjectId("507f1f77bcf86cd799439011"),
            local_path="/tmp/skills-repo",
        )
        await repo.insert()

        skill = Skill(
            name="git-skill-toggle-regression",
            description="Regression test skill",
            source="git",
            local_path="/tmp/skills-repo/git-skill-toggle-regression",
            enabled=True,
            git_repo_id=repo.id,
            mcp_config_id=None,
            last_synced_at=datetime.now(timezone.utc),
        )
        await skill.insert()

        resp = await client.patch(f"/api/v1/llm/skills/{skill.id}/toggle")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["id"] == str(skill.id)
        assert payload["enabled"] is False
        assert payload["git_repo_id"] == str(repo.id)
        assert payload["git_repo_url"] == repo.url
        assert payload["effective_mcp_config_id"] == str(repo.mcp_config_id)


class TestSummarySkillsCatalogSelection:
    async def test_webhook_summary_builds_catalog_with_explicit_none(self, client, monkeypatch, test_db):
        """One-shot summaries should call build_skills_catalog(active_mcp_config_ids=None)."""
        from types import SimpleNamespace

        import app.api.v1.llm as llm_api
        import app.modules.llm.services.context_service as context_service
        import app.modules.llm.services.llm_service_factory as llm_factory
        import app.modules.llm.services.prompt_builders as prompt_builders
        import app.modules.llm.services.skills_service as skills_service

        called: dict = {}

        async def _fake_build_skills_catalog(*args, **kwargs):
            called["args"] = args
            called["kwargs"] = kwargs
            return ""

        async def _fake_get_webhook_summary_context(hours: int):
            return "events summary", 3

        def _fake_build_webhook_summary_prompt(events_summary: str, hours: int, tz_name: str = "UTC"):
            return [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "summarize"},
            ]

        async def _fake_create_llm_service():
            return object()

        async def _fake_stream_or_complete(_llm, _messages, stream_id=None, json_mode=False):
            return SimpleNamespace(
                content="ok",
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

        async def _fake_log_llm_usage(*_args, **_kwargs):
            return None

        async def _fake_canvas_instructions() -> str:
            return ""

        monkeypatch.setattr(skills_service, "build_skills_catalog", _fake_build_skills_catalog)
        monkeypatch.setattr(context_service, "get_webhook_summary_context", _fake_get_webhook_summary_context)
        monkeypatch.setattr(prompt_builders, "build_webhook_summary_prompt", _fake_build_webhook_summary_prompt)
        monkeypatch.setattr(llm_factory, "create_llm_service", _fake_create_llm_service)
        monkeypatch.setattr(llm_api, "_stream_or_complete", _fake_stream_or_complete)
        monkeypatch.setattr(llm_api, "_log_llm_usage", _fake_log_llm_usage)
        monkeypatch.setattr(llm_api, "_get_canvas_instructions", _fake_canvas_instructions)

        resp = await client.post("/api/v1/llm/webhooks/summarize", json={"hours": 24})

        assert resp.status_code == 200
        assert called["args"] == ()
        assert called["kwargs"] == {"active_mcp_config_ids": None}

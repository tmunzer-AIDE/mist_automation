"""Tests for first-class Mistral provider support in the LLM module."""

import sys
from types import ModuleType, SimpleNamespace


def test_default_model_for_mistral():
    """Mistral provider gets a sensible default model."""
    from app.modules.llm.services.llm_service_factory import _default_model

    assert _default_model("mistral") == "mistral-small-latest"


def test_ssl_verify_can_be_disabled(monkeypatch):
    """Explicit env override can disable TLS verification for debugging."""
    from app.modules.llm.services.llm_service import _resolve_openai_ssl_verify

    monkeypatch.setenv("MIST_LLM_SSL_VERIFY", "false")
    assert _resolve_openai_ssl_verify() is False


def test_ssl_verify_uses_ca_bundle_env(monkeypatch):
    """CA bundle env var should be used when provided."""
    from app.modules.llm.services.llm_service import _resolve_openai_ssl_verify

    monkeypatch.delenv("MIST_LLM_SSL_VERIFY", raising=False)
    monkeypatch.setenv("MIST_LLM_CA_BUNDLE", "/tmp/corp-ca.pem")
    assert _resolve_openai_ssl_verify() == "/tmp/corp-ca.pem"


async def test_complete_uses_openai_client_with_mistral_default_url(monkeypatch):
    """Mistral provider should call OpenAI-compatible client with default base URL."""
    from app.modules.llm.services.llm_service import LLMMessage, LLMService

    captured: dict[str, object] = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model=kwargs["model"],
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="ok", tool_calls=None),
                        finish_reason="stop",
                    )
                ],
            )

    class FakeAsyncOpenAI:
        def __init__(self, api_key: str, base_url: str | None = None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            captured["closed"] = True

    fake_openai_module = ModuleType("openai")
    fake_openai_module.AsyncOpenAI = FakeAsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module)

    service = LLMService(provider="mistral", api_key="test", model="mistral-small-latest")
    response = await service.complete([LLMMessage(role="user", content="hello")])

    assert captured["api_key"] == "test"
    assert captured["base_url"] == "https://api.mistral.ai/v1"
    assert captured["model"] == "mistral-small-latest"
    assert captured["closed"] is True
    assert response.content == "ok"


async def test_fetch_models_mistral_uses_default_api_url(monkeypatch):
    """Model discovery should target Mistral's cloud API when no base_url is provided."""
    from app.api.v1.llm import _fetch_models

    captured: dict[str, object] = {}

    class FakeModelsClient:
        async def list(self):
            return SimpleNamespace(data=[SimpleNamespace(id="mistral-small-latest")])

    class FakeAsyncOpenAI:
        def __init__(self, api_key: str, base_url: str | None = None):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.models = FakeModelsClient()

        async def close(self):
            captured["closed"] = True

    fake_openai_module = ModuleType("openai")
    fake_openai_module.AsyncOpenAI = FakeAsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module)

    models = await _fetch_models("mistral", "secret-key", None)

    assert captured["api_key"] == "secret-key"
    assert captured["base_url"] == "https://api.mistral.ai/v1"
    assert captured["closed"] is True
    assert models[0]["id"] == "mistral-small-latest"

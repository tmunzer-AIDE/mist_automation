"""Tests for canvas_prompt_tier on LLMConfig and schemas."""
import pytest
from pydantic import ValidationError
from app.modules.llm.schemas import LLMConfigCreate, LLMConfigUpdate, LLMConfigResponse


def test_config_create_accepts_canvas_tier():
    config = LLMConfigCreate(name="test", provider="openai", canvas_prompt_tier="full")
    assert config.canvas_prompt_tier == "full"


def test_config_create_default_none():
    config = LLMConfigCreate(name="test", provider="openai")
    assert config.canvas_prompt_tier is None


def test_config_create_rejects_invalid_tier():
    with pytest.raises(ValidationError):
        LLMConfigCreate(name="test", provider="openai", canvas_prompt_tier="invalid")


def test_config_update_accepts_canvas_tier():
    update = LLMConfigUpdate(canvas_prompt_tier="explicit")
    assert update.canvas_prompt_tier == "explicit"


def test_config_response_includes_canvas_fields():
    resp = LLMConfigResponse(
        id="abc",
        name="test",
        provider="openai",
        api_key_set=True,
        model="gpt-4o",
        base_url=None,
        temperature=0.3,
        max_tokens_per_request=4096,
        context_window_tokens=None,
        context_window_effective=20000,
        is_default=True,
        enabled=True,
        canvas_prompt_tier=None,
        canvas_prompt_tier_effective="full",
    )
    assert resp.canvas_prompt_tier is None
    assert resp.canvas_prompt_tier_effective == "full"
    assert resp.context_window_tokens is None
    assert resp.context_window_effective == 20000

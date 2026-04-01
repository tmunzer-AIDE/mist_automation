"""Tests for canvas prompt tier auto-detection."""
import pytest
from app.modules.llm.services.llm_service_factory import _default_canvas_tier


def test_openai_gpt4_is_full():
    assert _default_canvas_tier("openai", "gpt-4o") == "full"
    assert _default_canvas_tier("openai", "gpt-4-turbo") == "full"


def test_openai_gpt35_is_explicit():
    assert _default_canvas_tier("openai", "gpt-3.5-turbo") == "explicit"


def test_anthropic_is_full():
    assert _default_canvas_tier("anthropic", "claude-sonnet-4-20250514") == "full"
    assert _default_canvas_tier("anthropic", None) == "full"


def test_vertex_gemini2_is_full():
    assert _default_canvas_tier("vertex", "gemini-2.0-flash") == "full"


def test_vertex_gemini1_is_explicit():
    assert _default_canvas_tier("vertex", "gemini-1.5-flash") == "explicit"


def test_bedrock_is_full():
    assert _default_canvas_tier("bedrock", "anthropic.claude-sonnet-4-20250514-v1:0") == "full"


def test_ollama_is_explicit():
    assert _default_canvas_tier("ollama", "llama3.1") == "explicit"


def test_lm_studio_is_explicit():
    assert _default_canvas_tier("lm_studio", "local-model") == "explicit"


def test_unknown_provider_defaults_to_explicit():
    assert _default_canvas_tier("unknown", "some-model") == "explicit"


def test_none_model_handled():
    assert _default_canvas_tier("ollama", None) == "explicit"
    assert _default_canvas_tier("openai", None) == "explicit"

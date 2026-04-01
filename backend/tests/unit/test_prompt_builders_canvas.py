"""Tests for canvas artifact prompt instructions."""
import pytest
from app.modules.llm.services.prompt_builders import build_canvas_instructions


def test_full_tier_contains_artifact_rules():
    result = build_canvas_instructions("full")
    assert "<artifact" in result
    assert "code" in result
    assert "markdown" in result
    assert "html" in result
    assert "mermaid" in result
    assert "svg" in result
    assert "chart" in result
    assert "title" in result


def test_explicit_tier_contains_example():
    result = build_canvas_instructions("explicit")
    assert "<artifact" in result
    assert "Example" in result or "example" in result
    assert "Do NOT wrap" in result or "do not wrap" in result.lower()


def test_none_tier_returns_empty():
    result = build_canvas_instructions("none")
    assert result == ""


def test_full_and_explicit_both_have_chart_spec():
    for tier in ("full", "explicit"):
        result = build_canvas_instructions(tier)
        assert "chartType" in result
        assert "datasets" in result

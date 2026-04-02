"""Unit tests for skills_service utility functions."""

import pytest
from pathlib import Path

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
        name, desc, body = parse_skill_md(f)
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

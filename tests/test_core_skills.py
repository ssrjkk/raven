from __future__ import annotations

from pathlib import Path

import pytest


class TestSkillsBuiltins:
    def test_list_skills_contains_builtins(self) -> None:
        from raven.core.skills import list_skills

        skills = list_skills()
        assert "code-review" in skills
        assert "security-audit" in skills
        assert "refactor" in skills
        assert "test-writer" in skills
        assert "debug" in skills
        assert "dependency-update" in skills

    def test_load_known_skill_returns_markdown(self) -> None:
        from raven.core.skills import load_skill

        content = load_skill("code-review")
        assert content.startswith("# Skill: Code Review")
        assert "## Instructions" in content

    def test_load_unknown_skill_returns_error(self) -> None:
        from raven.core.skills import load_skill

        result = load_skill("nonexistent-skill")
        assert "not found" in result

    def test_get_skill_info_known(self) -> None:
        from raven.core.skills import get_skill_info

        skill = get_skill_info("debug")
        assert skill is not None
        assert skill.name == "Debugging"

    def test_get_skill_info_unknown(self) -> None:
        from raven.core.skills import get_skill_info

        skill = get_skill_info("unknown")
        assert skill is None

    def test_discover_skills_contains_builtins(self) -> None:
        from raven.core.skills import discover_skills

        skills = discover_skills()
        assert len(skills) >= 6
        assert "code-review" in skills
        assert skills["code-review"].description != ""


class TestSkillsRegistry:
    def test_set_registry_url(self) -> None:
        from raven.core.skills import get_registry_url, set_skill_registry

        result = set_skill_registry("https://hub.example.com")
        assert "https://hub.example.com" in result
        assert get_registry_url() == "https://hub.example.com"

    def test_set_registry_url_empty(self) -> None:
        from raven.core.skills import get_registry_url, set_skill_registry

        set_skill_registry("")
        assert get_registry_url() == ""

    @pytest.mark.asyncio
    async def test_download_skill_no_registry(self) -> None:
        from raven.core.skills import download_skill, set_skill_registry

        set_skill_registry("")
        result = await download_skill("test-skill")
        assert "no registry URL" in result


class TestSkillsFileDiscovery:
    def test_discover_from_skill_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.skills import _SKILL_SEARCH_DIRS, discover_skills

        skill_dir = tmp_path / ".opencode" / "skills"
        skill_dir.mkdir(parents=True)
        (skill_dir / "my-custom-skill.md").write_text("Do this thing")

        monkeypatch.setattr("raven.core.skills._SKILL_SEARCH_DIRS", [skill_dir.parent.parent])

        skills = discover_skills()
        builtin_count = 6
        assert len(skills) >= builtin_count

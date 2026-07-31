from __future__ import annotations

from pathlib import Path

import pytest


class TestSkillsBuiltins:
    def test_list_skills_contains_builtins(self) -> None:
        from raven.core.skills import list_skills

        skills = list_skills()
        names = [s["name"] for s in skills]
        assert "code-review" in names
        assert "security-audit" in names
        assert "refactor" in names
        assert "test-writer" in names
        assert "debug" in names
        assert "dependency-update" in names

    def test_get_skill_info_known(self) -> None:
        from raven.core.skills import get_skill_info

        skill = get_skill_info("debug")
        assert skill is not None
        assert skill.name == "debug"
        assert skill.description != ""

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
        assert result is None

    def test_create_skill(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.skills import SKILLS_DIR, create_skill, get_skill_info

        monkeypatch.setattr("raven.core.skills.SKILLS_DIR", tmp_path / "skills")
        create_skill("test-skill", "A test skill", "do something")
        skill = get_skill_info("test-skill")
        assert skill is not None
        assert skill.description == "A test skill"

    def test_install_skill_from_md(self, tmp_path: Path) -> None:
        from raven.core.skills import install_skill

        md_file = tmp_path / "custom.md"
        md_file.write_text("# Custom skill\nDo the thing")
        skill = install_skill(str(md_file))
        assert skill is not None
        assert skill.name == "custom"


class TestSkillsFileDiscovery:
    def test_discover_from_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.skills import _SKILL_SEARCH_DIRS, SkillsRegistry

        skill_dir = tmp_path / "skills" / "my-custom"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text("# My Custom\nDo this thing")
        reg = SkillsRegistry()
        count = reg.register_from_dir(tmp_path / "skills")
        assert count >= 1
        skill = reg.get("my-custom")
        assert skill is not None
        assert "My Custom" in skill.description

from __future__ import annotations

from pathlib import Path

from ravencode.runtime.skills import discover_skills, load_skill


class TestDiscoverSkills:
    def test_discover_returns_dict(self):
        skills = discover_skills()
        assert isinstance(skills, dict)

    def test_discover_includes_builtins(self):
        skills = discover_skills()
        assert "code-review" in skills
        assert "debug" in skills
        assert "test-writer" in skills

    def test_discover_includes_raven_artifacts(self, tmp_path: Path):
        skill_dir = tmp_path / ".raven" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: My custom skill\n---\nDo the thing", encoding="utf-8"
        )
        skills = discover_skills(cwd=tmp_path)
        assert "my-skill" in skills


class TestLoadSkill:
    def test_load_nonexistent(self):
        result = load_skill("nonexistent_skill_xyz")
        assert "not found" in result

    def test_load_from_raven_layer(self, tmp_path: Path):
        skill_dir = tmp_path / ".raven" / "skills" / "testskill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: Test Skill\n---\nDo something useful", encoding="utf-8"
        )
        result = load_skill("testskill", cwd=tmp_path)
        assert "Test Skill" in result
        assert "Do something useful" in result

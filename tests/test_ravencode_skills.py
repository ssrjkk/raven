from __future__ import annotations

from pathlib import Path

from ravencode.runtime.skills import _SKILL_SEARCH_DIRS, discover_skills, load_skill


class TestDiscoverSkills:
    def test_discover_returns_dict(self):
        skills = discover_skills()
        assert isinstance(skills, dict)

    def test_discover_includes_builtins(self):
        skills = discover_skills()
        assert "code-review" in skills
        assert "debug" in skills
        assert "test-writer" in skills


class TestLoadSkill:
    def test_load_nonexistent(self):
        result = load_skill("nonexistent_skill_xyz")
        assert "not found" in result

    def test_load_from_file_in_search_dir(self, tmp_path: Path):
        search_dir = tmp_path / "myskills"
        search_dir.mkdir()
        (search_dir / "testskill.md").write_text("# Test Skill\n\nDo something")
        orig_dirs = list(_SKILL_SEARCH_DIRS)
        try:
            _SKILL_SEARCH_DIRS.clear()
            _SKILL_SEARCH_DIRS.append(search_dir)
            result = load_skill("testskill")
            assert "Test Skill" in result
        finally:
            _SKILL_SEARCH_DIRS.clear()
            _SKILL_SEARCH_DIRS.extend(orig_dirs)

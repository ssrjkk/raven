from __future__ import annotations

from pathlib import Path

from raven.core.skills import Skill, SkillsRegistry, skills_registry


def test_skill_create():
    skill = Skill(name="test", description="A test skill", instructions="Do X")
    assert skill.name == "test"
    assert skill.description == "A test skill"
    assert skill.instructions == "Do X"


def test_skills_registry_register():
    reg = SkillsRegistry()
    skill = Skill(name="code", description="Write code", instructions="Generate code")
    reg.register(skill)
    assert reg.get("code") is skill


def test_skills_registry_list():
    reg = SkillsRegistry()
    reg.register(Skill(name="a", description="", instructions=""))
    reg.register(Skill(name="b", description="", instructions=""))
    assert len(reg.list_names()) == 2
    assert set(reg.list_names()) == {"a", "b"}


def test_skills_registry_get_unknown():
    reg = SkillsRegistry()
    assert reg.get("nonexistent") is None


def test_skills_registry_remove():
    reg = SkillsRegistry()
    reg.register(Skill(name="z", description="", instructions=""))
    assert reg.remove("z") is True
    assert reg.get("z") is None


def test_skills_registry_remove_nonexistent():
    reg = SkillsRegistry()
    assert reg.remove("nonexistent") is False


def test_skills_registry_from_dir(tmp_path: Path):
    (tmp_path / "my-skill.md").write_text("My custom skill\n\nDo something useful")
    reg = SkillsRegistry()
    reg.register_from_dir(tmp_path)
    skill = reg.get("my-skill")
    assert skill is not None
    assert "My custom skill" in skill.instructions


def test_skills_registry_from_dir_nonexistent():
    reg = SkillsRegistry()
    reg.register_from_dir(Path("/nonexistent"))
    assert reg.list_names() == []


def test_skills_registry_from_dir_no_skill_file(tmp_path: Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    reg = SkillsRegistry()
    reg.register_from_dir(tmp_path)
    assert reg.list_names() == []


def test_skills_registry_global():
    for name in skills_registry.list_names():
        skills_registry.remove(name)
    assert skills_registry.list_names() == []

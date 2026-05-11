from __future__ import annotations
import tempfile
from pathlib import Path
from raven.core.skills import Skill, SkillsRegistry, skills_registry


def test_skill_create():
    skill = Skill(name="test", description="A test skill", prompt="Do X")
    assert skill.name == "test"
    assert skill.description == "A test skill"


def test_skill_to_dict():
    skill = Skill(name="test", description="A test skill", prompt="Do X and Y")
    d = skill.to_dict()
    assert d["name"] == "test"
    assert d["description"] == "A test skill"


def test_skills_registry_register():
    reg = SkillsRegistry()
    skill = Skill(name="code", description="Write code", prompt="Generate code")
    reg.register(skill)
    assert reg.get("code") is skill


def test_skills_registry_list():
    reg = SkillsRegistry()
    reg.register(Skill(name="a", description="", prompt=""))
    reg.register(Skill(name="b", description="", prompt=""))
    assert len(reg.list()) == 2
    assert set(reg.list_names()) == {"a", "b"}


def test_skills_registry_active_prompts():
    reg = SkillsRegistry()
    reg.register(Skill(name="x", description="desc", prompt="do x"))
    active = reg.active_prompts(["x"])
    assert "do x" in active
    assert "Skill: x" in active


def test_skills_registry_active_prompts_empty():
    reg = SkillsRegistry()
    assert reg.active_prompts([]) == ""
    assert reg.active_prompts(["nonexistent"]) == ""


def test_skills_registry_get_prompt():
    reg = SkillsRegistry()
    reg.register(Skill(name="y", description="", prompt="hello"))
    assert reg.get_prompt("y") == "hello"
    assert reg.get_prompt("nonexistent") == ""


def test_skills_registry_clear():
    reg = SkillsRegistry()
    reg.register(Skill(name="z", description="", prompt=""))
    reg.clear()
    assert reg.list() == []


def test_skills_registry_from_dir(tmp_path: Path):
    skill_dir = tmp_path / "my_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("My custom skill\n\nDo something useful")
    reg = SkillsRegistry()
    reg.register_from_dir(tmp_path)
    skill = reg.get("my_skill")
    assert skill is not None
    assert "My custom skill" in skill.prompt


def test_skills_registry_from_dir_nonexistent():
    reg = SkillsRegistry()
    reg.register_from_dir(Path("/nonexistent"))
    assert reg.list() == []


def test_skills_registry_from_dir_no_skill_file(tmp_path: Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    reg = SkillsRegistry()
    reg.register_from_dir(tmp_path)
    assert reg.list() == []


def test_skills_registry_global():
    skills_registry.clear()
    assert skills_registry.list() == []

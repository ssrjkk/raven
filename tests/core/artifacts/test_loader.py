from __future__ import annotations

from pathlib import Path

from raven.core.artifacts import loader
from raven.core.artifacts.frontmatter import parse_frontmatter


def _make_skill(base: Path, name: str, meta: str, body: str) -> Path:
    d = base / name
    d.mkdir(parents=True)
    f = d / "SKILL.md"
    f.write_text(f"---\n{meta}\n---\n{body}", encoding="utf-8")
    return f


def test_parse_frontmatter() -> None:
    meta, body = parse_frontmatter("---\ndescription: hi\nagents: [coder]\n---\nbody text")
    assert meta == {"description": "hi", "agents": ["coder"]}
    assert body == "body text"


def test_parse_frontmatter_no_frontmatter() -> None:
    meta, body = parse_frontmatter("just text")
    assert meta == {}
    assert body == "just text"


def test_skill_index_is_lazy(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha", "description: Alpha skill\nactivation: manual", "BIG INSTRUCTIONS")
    indexes = list(loader.iter_skills([tmp_path]))
    assert len(indexes) == 1
    index = indexes[0]
    assert index.name == "alpha"
    assert index.activation == "manual"
    assert "BIG INSTRUCTIONS" not in index.description


def test_load_skill_full(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha", "description: Alpha skill", "Do the thing.\n")
    index = next(loader.iter_skills([tmp_path]))
    skill = loader.load_skill(index)
    assert "Do the thing." in skill.instructions
    assert skill.examples == []


def test_load_skill_with_examples_and_scripts(tmp_path: Path) -> None:
    d = tmp_path / "alpha"
    d.mkdir()
    (d / "SKILL.md").write_text("# Alpha\nbody", encoding="utf-8")
    (d / "examples.md").write_text("example one", encoding="utf-8")
    scripts = d / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("print(1)", encoding="utf-8")
    index = next(loader.iter_skills([tmp_path]))
    skill = loader.load_skill(index)
    assert skill.examples == ["example one"]
    assert any(p.name == "run.py" for p in skill.paths)


def test_iter_commands_with_materials(tmp_path: Path) -> None:
    cmd = tmp_path / "shipit"
    cmd.mkdir()
    (cmd / "command.md").write_text(
        "---\ndescription: Ship\nrefs: [notes.md]\n---\nDeploy $ARGUMENTS\n", encoding="utf-8"
    )
    (cmd / "notes.md").write_text("checklist", encoding="utf-8")
    (cmd / "materials").mkdir()
    (cmd / "materials" / "runbook.md").write_text("runbook content", encoding="utf-8")

    indexes = list(loader.iter_commands([tmp_path]))
    assert len(indexes) == 1
    index = indexes[0]
    assert index.name == "shipit"
    assert index.refs == ["notes.md"]
    assert index.materials_dir is not None

    bundle = loader.load_command(index)
    assert bundle.prompt == "Deploy $ARGUMENTS"
    assert bundle.material_names() == ["runbook"]
    assert bundle.material_path("runbook") is not None


def test_iter_rules_dir_scope(tmp_path: Path) -> None:
    rules = tmp_path / "rules"
    (rules / "sub").mkdir(parents=True)
    (rules / "root.md").write_text("# Root", encoding="utf-8")
    (rules / "sub" / "nested.md").write_text("---\nprecedence: 5\n---\nnested body", encoding="utf-8")

    found = {r.name: r for r in loader.iter_rules([rules])}
    assert found["root"].dir_scope == ""
    assert found["nested"].dir_scope == "sub"
    assert found["nested"].precedence == 5
    assert "nested body" in found["nested"].content


def test_import_agents_md_scoped(tmp_path: Path) -> None:
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("root rules", encoding="utf-8")
    (tmp_path / "src" / "api" / "AGENTS.md").write_text("api rules", encoding="utf-8")

    rules = list(loader.import_agents_md(tmp_path))
    assert len(rules) == 2
    by_scope = {r.dir_scope: r for r in rules}
    assert by_scope[""] is not None
    assert by_scope["src/api"] is not None
    assert "api rules" in by_scope["src/api"].content


def test_import_agents_md_skips_vendored_dirs(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "AGENTS.md").write_text("skip", encoding="utf-8")
    rules = list(loader.import_agents_md(tmp_path))
    assert rules == []


def test_iter_agents(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    (agents / "reviewer").mkdir(parents=True)
    (agents / "reviewer" / "agent.md").write_text(
        "---\ndescription: Reviewer\nallowed_tools: [read_file, grep]\n---\nYou review code.\n",
        encoding="utf-8",
    )
    found = {a.name: a for a in loader.iter_agents([agents])}
    assert "reviewer" in found
    agent = found["reviewer"]
    assert agent.allowed_tools == ["read_file", "grep"]
    assert "You review code." in agent.system_prompt

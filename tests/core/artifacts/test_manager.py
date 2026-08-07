from __future__ import annotations

import asyncio
from pathlib import Path

from raven.core.artifacts.commands import render_command
from raven.core.artifacts.manager import ArtifactManager


def _skill(base: Path, name: str, meta: str, body: str) -> None:
    d = base / ".raven" / "skills" / name
    d.mkdir(parents=True)
    d.joinpath("SKILL.md").write_text(f"---\n{meta}\n---\n{body}", encoding="utf-8")


def _command(base: Path, name: str, frontmatter: str, body: str, materials: dict[str, str] | None = None) -> None:
    d = base / ".raven" / "commands" / name
    d.mkdir(parents=True)
    d.joinpath("command.md").write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    if materials:
        (d / "materials").mkdir(exist_ok=True)
        for mname, content in materials.items():
            d.joinpath("materials", f"{mname}.md").write_text(content, encoding="utf-8")


def test_skills_for_scoping_and_lazy_load(tmp_path: Path) -> None:
    _skill(tmp_path, "alpha", "description: Alpha", "ALPHA BODY")
    _skill(tmp_path, "secret", "description: Secret\nagents: [coder]\nactivation: manual", "SECRET BODY")
    m = ArtifactManager(cwd=tmp_path)

    ctx = m.context(agent_id="assistant", cwd=tmp_path, root=tmp_path)
    skills = m.skills_for(ctx)
    assert [s.name for s in skills] == ["alpha"]

    coder_ctx = m.context(agent_id="coder", cwd=tmp_path, root=tmp_path)
    coder_skills = m.skills_for(coder_ctx)
    assert {s.name for s in coder_skills} == {"alpha"}


def test_command_bundle_scope(tmp_path: Path) -> None:
    _command(tmp_path, "shipit", "description: Ship it", "Deploy $ARGUMENTS")
    _command(tmp_path, "codeonly", "description: Coder\nagents: [coder]", "Code only")
    m = ArtifactManager(cwd=tmp_path)

    ctx = m.context(agent_id="assistant", command="shipit", cwd=tmp_path, root=tmp_path)
    names = [c.name for c in m.commands_for(ctx)]
    assert "shipit" in names
    assert "codeonly" not in names

    assert m.command_bundle_for("shipit", ctx) is not None
    assert m.command_bundle_for("codeonly", ctx) is None


def test_private_agent_dirs_override(tmp_path: Path) -> None:
    _skill(tmp_path, "base", "description: Base", "BASE")
    private = tmp_path / ".raven" / "agents" / "coder" / "skills" / "private-skill"
    private.mkdir(parents=True)
    private.joinpath("SKILL.md").write_text("---\ndescription: Private\n---\nPRIVATE BODY", encoding="utf-8")

    m = ArtifactManager(cwd=tmp_path)
    ctx = m.context(agent_id="coder", cwd=tmp_path, root=tmp_path)
    skills = {s.name: s for s in m.skills_for(ctx)}
    assert "private-skill" in skills
    assert "PRIVATE BODY" in skills["private-skill"].instructions


def test_rules_for_ordering_and_scoping(tmp_path: Path) -> None:
    rules = tmp_path / ".raven" / "rules"
    rules.mkdir(parents=True)
    (rules / "root.md").write_text("# Root rules", encoding="utf-8")
    (rules / "web").mkdir()
    (rules / "web" / "ui.md").write_text("# UI rules", encoding="utf-8")
    (rules / "core.md").write_text(
        "---\nagents: [coder]\n---\n# Coder only", encoding="utf-8"
    )
    m = ArtifactManager(cwd=tmp_path)

    ctx = m.context(agent_id="assistant", cwd=tmp_path / "web", root=tmp_path)
    rules_ctx = m.rules_for(ctx)
    names = [r.name for r in rules_ctx]
    assert "ui" in names
    assert "core" not in names
    assert names[0] == "root" and names[1] == "ui"


def test_agents_md_import_as_rules(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("team-wide rules", encoding="utf-8")
    m = ArtifactManager(cwd=tmp_path)
    ctx = m.context(agent_id="assistant", cwd=tmp_path, root=tmp_path)
    rules = m.rules_for(ctx)
    assert any("team-wide rules" in r.content for r in rules)


def test_render_command_with_args_refs_materials(tmp_path: Path) -> None:
    d = tmp_path / ".raven" / "commands" / "shipit"
    d.mkdir(parents=True)
    d.joinpath("command.md").write_text(
        "---\ndescription: Ship\nrefs: [check.md]\n---\nDeploy $ARGUMENTS and $1\n", encoding="utf-8"
    )
    d.joinpath("check.md").write_text("checklist", encoding="utf-8")
    (d / "materials").mkdir()
    d.joinpath("materials", "runbook.md").write_text("runbook", encoding="utf-8")

    m = ArtifactManager(cwd=tmp_path)
    ctx = m.context(agent_id="assistant", cwd=tmp_path, root=tmp_path)
    bundle = m.command_bundle_for("shipit", ctx)
    assert bundle is not None
    rendered = asyncio.run(render_command(bundle, ["api", "v1"]))
    assert "Deploy api v1 and api" in rendered
    assert "checklist" in rendered
    assert "runbook" in rendered


def test_refresh_reindexes(tmp_path: Path) -> None:
    m = ArtifactManager(cwd=tmp_path)
    assert m.skills_index() == []
    _skill(tmp_path, "late", "description: Late", "LATE BODY")
    m.refresh()
    assert [s.name for s in m.skills_index()] == ["late"]

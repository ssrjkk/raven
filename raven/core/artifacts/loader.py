"""Lazy artifact discovery and loading.

Discovery reads only file frontmatter (cheap indexes). Full contents
(instructions, command prompts, rule bodies) are read on demand via
``load_skill`` / ``load_command`` / rule loading in the manager.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from raven.core.artifacts.frontmatter import parse_frontmatter
from raven.core.artifacts.model import (
    AgentDef,
    ArtifactScope,
    CommandBundle,
    Rule,
    ScopedSkill,
    ScopeLayer,
)

_GENERIC_SKIP = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".raven.local",
}

_AGENTS_MD_SKIP = _GENERIC_SKIP | {"data", "web", "dist", "build"}

_SKILL_FILES = ("SKILL.md", "skill.md")
_AGENT_FILES = ("agent.md", "AGENT.md", "agent.yaml", "agent.yml", "agent.json")


@dataclass
class SkillIndex:
    name: str
    description: str
    source: Path
    layer: ScopeLayer = ScopeLayer.TEAM
    scope: ArtifactScope = field(default_factory=ArtifactScope)
    activation: str = "auto"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandIndex:
    name: str
    description: str
    source: Path
    layer: ScopeLayer = ScopeLayer.TEAM
    scope: ArtifactScope = field(default_factory=ArtifactScope)
    agent: str = ""
    model: str = ""
    refs: list[str] = field(default_factory=list)
    materials_dir: Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _scope_from_meta(meta: dict[str, Any]) -> ArtifactScope:
    raw = meta.get("scope")
    merged: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    for key in ("agents", "roles", "commands", "paths", "task_types", "channels", "when", "enabled"):
        if key in meta:
            merged[key] = meta[key]
    return ArtifactScope.from_dict(merged)


def _layer_from_meta(meta: dict[str, Any], fallback: ScopeLayer) -> ScopeLayer:
    raw = str(meta.get("layer", "")).lower()
    if raw in ScopeLayer.__members__.values():
        return ScopeLayer(raw)
    return fallback


def _iter_children(base: Path) -> Iterator[Path]:
    for root in base.rglob("*"):
        if root.is_file():
            yield root


def iter_skills(paths: list[Path], layer: ScopeLayer = ScopeLayer.TEAM) -> Iterator[SkillIndex]:
    seen: set[Path] = set()
    for base in paths:
        if base.resolve() in seen:
            continue
        seen.add(base.resolve())
        if not base.is_dir():
            continue
        for skill_file in _iter_children(base):
            if skill_file.name not in _SKILL_FILES or _is_skipped(skill_file, base):
                continue
            meta, _ = parse_frontmatter(skill_file.read_text(encoding="utf-8", errors="replace"))
            name = str(meta.get("name") or skill_file.parent.name).strip()
            description = str(meta.get("description") or _first_heading(_read_skill_body(skill_file)) or name)
            yield SkillIndex(
                name=name,
                description=description,
                source=skill_file,
                layer=_layer_from_meta(meta, layer),
                scope=_scope_from_meta(meta),
                activation=str(meta.get("activation", "auto")).lower(),
                meta=meta,
            )


def load_skill(index: SkillIndex) -> ScopedSkill:
    source = index.source
    instructions = source.read_text(encoding="utf-8", errors="replace")
    _, body = parse_frontmatter(instructions)
    examples: list[str] = []
    examples_file = source.parent / "examples.md"
    if examples_file.exists():
        examples = [examples_file.read_text(encoding="utf-8", errors="replace")]
    scripts_dir = source.parent / "scripts"
    paths: list[Path] = [source]
    if scripts_dir.is_dir():
        for sp in sorted(scripts_dir.iterdir()):
            if sp.suffix in (".py", ".sh", ".ps1"):
                paths.append(sp)
    return ScopedSkill(
        name=index.name,
        description=index.description,
        scope=index.scope,
        source=source,
        layer=index.layer,
        instructions=body,
        examples=examples,
        activation=index.activation,
        paths=paths,
    )


def _read_skill_body(skill_file: Path) -> str:
    _, body = parse_frontmatter(skill_file.read_text(encoding="utf-8", errors="replace"))
    return body


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and len(stripped) > 2:
            return stripped[2:].strip()
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return lines[0][:120] if lines else ""


def iter_commands(paths: list[Path], layer: ScopeLayer = ScopeLayer.TEAM) -> Iterator[CommandIndex]:
    seen: set[Path] = set()
    for base in paths:
        if base.resolve() in seen:
            continue
        seen.add(base.resolve())
        if not base.is_dir():
            continue
        for source in _iter_children(base):
            if _is_skipped(source, base):
                continue
            if source.name != "command.md":
                continue
            meta, _ = parse_frontmatter(source.read_text(encoding="utf-8", errors="replace"))
            name = str(meta.get("name") or source.parent.name).strip()
            description = str(meta.get("description") or name)
            materials_dir = source.parent / "materials" if (source.parent / "materials").is_dir() else None
            refs = meta.get("refs", [])
            if isinstance(refs, str):
                refs = [refs]
            yield CommandIndex(
                name=name,
                description=description,
                source=source,
                layer=_layer_from_meta(meta, layer),
                scope=_scope_from_meta(meta),
                agent=str(meta.get("agent", "")),
                model=str(meta.get("model", "")),
                refs=[str(r) for r in refs],
                materials_dir=materials_dir,
                meta=meta,
            )


def load_command(index: CommandIndex) -> CommandBundle:
    text = index.source.read_text(encoding="utf-8", errors="replace")
    _, prompt = parse_frontmatter(text)
    materials: dict[str, Path] = {}
    if index.materials_dir is not None:
        for mp in sorted(index.materials_dir.iterdir()):
            if mp.is_file():
                materials[mp.stem] = mp
    return CommandBundle(
        name=index.name,
        description=index.description,
        scope=index.scope,
        source=index.source,
        layer=index.layer,
        prompt=prompt,
        agent=index.agent,
        model=index.model,
        refs=[Path(r) for r in index.refs],
        materials_dir=index.materials_dir,
        _materials=materials,
    )


def iter_rules(paths: list[Path], layer: ScopeLayer = ScopeLayer.TEAM) -> Iterator[Rule]:
    seen: set[Path] = set()
    for base in paths:
        if base.resolve() in seen:
            continue
        seen.add(base.resolve())
        if not base.is_dir():
            continue
        for source in _iter_children(base):
            if source.suffix not in (".md", ".markdown", ".mdc") or _is_skipped(source, base):
                continue
            meta, body = parse_frontmatter(source.read_text(encoding="utf-8", errors="replace"))
            try:
                rel_dir = source.parent.relative_to(base).as_posix()
            except ValueError:
                rel_dir = ""
            dir_scope = "" if rel_dir in ("", ".") else rel_dir
            try:
                precedence = int(meta.get("precedence", 100))
            except (TypeError, ValueError):
                precedence = 100
            yield Rule(
                name=str(meta.get("name") or source.stem),
                description=str(meta.get("description") or source.stem),
                scope=_scope_from_meta(meta),
                source=source,
                layer=_layer_from_meta(meta, layer),
                content=body,
                dir_scope=dir_scope,
                precedence=precedence,
            )


def import_agents_md(root: Path, max_depth: int = 6) -> Iterator[Rule]:
    """Import existing ``AGENTS.md`` files as directory-scoped team rules."""
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if len(rel.parts) > max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _AGENTS_MD_SKIP and not d.startswith(".")]
        if "AGENTS.md" in filenames:
            source = Path(dirpath) / "AGENTS.md"
            yield Rule(
                name=f"AGENTS.md@{rel.as_posix() if rel.parts else '.'}",
                description=f"Directory rules for {rel.as_posix() if rel.parts else '.'}",
                source=source,
                layer=ScopeLayer.TEAM,
                content=source.read_text(encoding="utf-8", errors="replace"),
                dir_scope=rel.as_posix() if rel.parts else "",
                precedence=90,
            )


def iter_agents(paths: list[Path], layer: ScopeLayer = ScopeLayer.TEAM) -> Iterator[AgentDef]:
    seen: set[Path] = set()
    for base in paths:
        if base.resolve() in seen:
            continue
        seen.add(base.resolve())
        if not base.is_dir():
            continue
        for source in _iter_children(base):
            if source.name not in _AGENT_FILES or _is_skipped(source, base):
                continue
            meta: dict[str, Any] = {}
            body = ""
            if source.suffix in (".md", ".yaml", ".yml"):
                text = source.read_text(encoding="utf-8", errors="replace")
                meta, body = parse_frontmatter(text)
                if not meta and source.suffix in (".yaml", ".yml"):
                    meta = _parse_yaml(text)
            elif source.suffix == ".json":
                meta = _parse_json(source)
            name = str(meta.get("name") or source.parent.name).strip()
            allowed = meta.get("allowed_tools", meta.get("tools", []))
            denied = meta.get("denied_tools", meta.get("restricted_tools", []))
            yield AgentDef(
                name=name,
                description=str(meta.get("description") or name),
                scope=_scope_from_meta(meta),
                source=source,
                layer=_layer_from_meta(meta, layer),
                system_prompt=body or str(meta.get("system_prompt", "")),
                model=str(meta.get("model", "")),
                allowed_tools=[str(t) for t in allowed] if isinstance(allowed, list) else [],
                denied_tools=[str(t) for t in denied] if isinstance(denied, list) else [],
                max_iterations=int(meta.get("max_iterations", 10)),
            )


def _parse_yaml(text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def _parse_json(source: Path) -> dict[str, Any]:
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_skipped(path: Path, base: Path) -> bool:
    try:
        parts = path.relative_to(base).parts
    except ValueError:
        return False
    return any(part in _GENERIC_SKIP or part.startswith(".") for part in parts[:-1])

"""Artifact model: scope, layered metadata and runtime context.

Artifacts are the building blocks of the agent workspace: skills, commands,
rules and agent definitions. Every artifact carries an :class:`ArtifactScope`
so the runtime can decide declaratively whether it applies to the current
context (agent, role, channel, command, task type, paths).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ArtifactKind(StrEnum):
    SKILL = "skill"
    COMMAND = "command"
    RULE = "rule"
    AGENT = "agent"
    PLUGIN = "plugin"
    HOOK = "hook"


class ScopeLayer(StrEnum):
    GLOBAL = "global"
    TEAM = "team"
    LOCAL = "local"
    CONFIG = "config"
    ENV = "env"


@dataclass
class ArtifactScope:
    """Declarative applicability of an artifact.

    Empty lists are wildcards (apply everywhere). An artifact applies only if
    every non-empty constraint matches the runtime context.
    """

    agents: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    when: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> ArtifactScope:
        raw = data if isinstance(data, dict) else {}
        scope = cls()
        for key in ("agents", "roles", "commands", "paths", "task_types", "channels"):
            value = raw.get(key)
            if isinstance(value, str):
                setattr(scope, key, [value])
            elif isinstance(value, list):
                setattr(scope, key, [str(v) for v in value if v is not None])
        scope.when = str(raw.get("when", ""))
        enabled = raw.get("enabled", True)
        scope.enabled = enabled if isinstance(enabled, bool) else True
        return scope


@dataclass
class Artifact:
    name: str
    description: str = ""
    scope: ArtifactScope = field(default_factory=ArtifactScope)
    source: Path | None = None
    layer: ScopeLayer = ScopeLayer.TEAM
    kind: ArtifactKind = ArtifactKind.SKILL


@dataclass
class ArtifactContext:
    """Runtime context used to match artifact scopes."""

    agent_id: str = "default"
    role: str = ""
    channel: str = ""
    command: str | None = None
    task_type: str | None = None
    cwd: Path = field(default_factory=Path.cwd)
    root: Path = field(default_factory=Path.cwd)
    text: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScopedSkill(Artifact):
    kind: ArtifactKind = ArtifactKind.SKILL
    instructions: str = ""
    examples: list[str] = field(default_factory=list)
    activation: str = "auto"
    paths: list[Path] = field(default_factory=list)


@dataclass
class CommandBundle(Artifact):
    kind: ArtifactKind = ArtifactKind.COMMAND
    prompt: str = ""
    agent: str = ""
    model: str = ""
    refs: list[Path] = field(default_factory=list)
    materials_dir: Path | None = None
    _materials: dict[str, Path] = field(default_factory=dict)

    def material_names(self) -> list[str]:
        return list(self._materials.keys())

    def material_path(self, name: str) -> Path | None:
        return self._materials.get(name)


@dataclass
class Rule(Artifact):
    kind: ArtifactKind = ArtifactKind.RULE
    content: str = ""
    dir_scope: str = ""
    precedence: int = 100


@dataclass
class AgentDef(Artifact):
    """Agent definition artifact: a role with its own artifacts and tools."""

    kind: ArtifactKind = ArtifactKind.AGENT
    system_prompt: str = ""
    model: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    max_iterations: int = 10


def relpath_under(root: Path, path: Path) -> str:
    """Return path relative to root, falling back to the basename."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def path_matches(scope_paths: list[str], rel: str, name: str) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern) for pattern in scope_paths)

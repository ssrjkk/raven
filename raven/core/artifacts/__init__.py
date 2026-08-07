"""Artifact layer: scoped, layered, lazy agent artifacts.

Layers (highest precedence first): env -> raven.json ``paths`` -> personal
``.raven.local`` -> team ``.raven`` -> global ``~/.config/raven`` -> legacy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from raven.core.artifacts.manager import ArtifactManager
from raven.core.artifacts.model import (
    AgentDef,
    Artifact,
    ArtifactContext,
    ArtifactKind,
    ArtifactScope,
    CommandBundle,
    Rule,
    ScopedSkill,
    ScopeLayer,
)
from raven.core.artifacts.scope import ScopeMatcher, scope_matcher

__all__ = [
    "AgentDef",
    "Artifact",
    "ArtifactContext",
    "ArtifactKind",
    "ArtifactManager",
    "ArtifactScope",
    "CommandBundle",
    "Rule",
    "ScopeLayer",
    "ScopeMatcher",
    "ScopedSkill",
    "get_artifact_manager",
    "scope_matcher",
]

_manager_cache: dict[str, ArtifactManager] = {}


def get_artifact_manager(
    *,
    cwd: Path | None = None,
    config: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> ArtifactManager:
    """Return the process-wide artifact manager for a working directory."""
    key = str(Path(cwd or Path.cwd()).resolve())
    manager = _manager_cache.get(key)
    if manager is None:
        manager = ArtifactManager(cwd=cwd, config=config, env=env)
        _manager_cache[key] = manager
    return manager

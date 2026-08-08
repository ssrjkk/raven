"""Configurable artifact paths with layered resolution.

Resolution order (highest precedence first) per artifact kind:

1. environment overrides  ``RAVEN_<KIND>_DIR`` / ``<KIND>_DIR``
2. ``raven.json`` -> ``paths.<kind>``
3. personal layer      ``<cwd>/.raven.local/<kind>``
4. team layer          ``<cwd>/.raven/<kind>``
5. global layer        ``~/.config/raven/<kind>``
6. legacy compat dirs  (``.opencode``, ``.claude``, ``.agents``, workspace)

No path is hardcoded: every layer can be replaced or extended via env / config.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KINDS = ("skills", "commands", "rules", "agents", "plugins", "hooks")

_LEGACY: dict[str, list[str]] = {
    "skills": ["workspace/skills", ".opencode/skills", ".claude/skills", ".agents/skills"],
    "commands": [".opencode/commands"],
    "rules": [],
    "agents": [],
    "plugins": ["plugins", ".opencode/plugin"],
    "hooks": [],
}

_LEGACY_HOME: dict[str, list[str]] = {
    "skills": [".config/opencode/skills"],
    "commands": [".config/opencode/commands"],
    "rules": [],
    "agents": [],
    "plugins": [],
    "hooks": [],
}


@dataclass
class ArtifactPaths:
    skills: list[Path] = field(default_factory=list)
    commands: list[Path] = field(default_factory=list)
    rules: list[Path] = field(default_factory=list)
    agents: list[Path] = field(default_factory=list)
    plugins: list[Path] = field(default_factory=list)
    hooks: list[Path] = field(default_factory=list)

    def for_kind(self, kind: str) -> list[Path]:
        return list(getattr(self, kind, []))

    @classmethod
    def resolve(
        cls,
        cwd: Path | None = None,
        config: dict[str, Any] | None = None,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> ArtifactPaths:
        env = env if env is not None else os.environ
        cwd = Path(cwd or Path.cwd())
        home = home or Path.home()
        cfg_paths = _read_raven_json(cwd, env).get("paths", {})
        out: dict[str, list[Path]] = {}
        for kind in KINDS:
            dirs: list[Path] = []
            dirs.extend(_env_dirs(kind, env, cwd))
            dirs.extend(_config_dirs(kind, cfg_paths, cwd))
            dirs.append(cwd / ".raven.local" / kind)
            dirs.append(cwd / ".raven" / kind)
            dirs.append(home / ".config" / "raven" / kind)
            dirs.extend(_legacy_dirs(kind, cwd))
            dirs.extend(_legacy_home_dirs(kind, home))
            out[kind] = _dedupe_existing(dirs)
        return cls(
            skills=out["skills"],
            commands=out["commands"],
            rules=out["rules"],
            agents=out["agents"],
            plugins=out["plugins"],
            hooks=out["hooks"],
        )


def _env_dirs(kind: str, env: Mapping[str, str], cwd: Path) -> list[Path]:
    key = f"RAVEN_{kind.upper()}_DIR"
    plain = f"{kind.upper()}_DIR"
    raw = env.get(key) or env.get(plain) or ""
    return _split_paths(raw, cwd)


def _config_dirs(kind: str, cfg_paths: dict[str, Any], cwd: Path) -> list[Path]:
    value = cfg_paths.get(kind, [])
    if isinstance(value, str):
        return _split_paths(value, cwd)
    if isinstance(value, list):
        return _split_paths(";".join(str(v) for v in value), cwd)
    return []


def _legacy_dirs(kind: str, cwd: Path) -> list[Path]:
    return [Path(d) if Path(d).is_absolute() else cwd / d for d in _LEGACY.get(kind, [])]


def _legacy_home_dirs(kind: str, home: Path) -> list[Path]:
    return [home / d for d in _LEGACY_HOME.get(kind, [])]


def _split_paths(raw: str, cwd: Path | None = None) -> list[Path]:
    if not raw:
        return []
    out: list[Path] = []
    for part in raw.replace(";", ",").split(","):
        p = part.strip()
        if not p:
            continue
        path = Path(p)
        if cwd is not None and not path.is_absolute():
            path = cwd / path
        out.append(path)
    return out


def _dedupe_existing(dirs: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for d in dirs:
        key = str(d.resolve())
        if key in seen:
            continue
        seen.add(key)
        if d.is_dir():
            result.append(d)
    return result


def _read_raven_json(cwd: Path, env: Mapping[str, str]) -> dict[str, Any]:
    candidates = [Path(env.get("RAVEN_CONFIG", "")), cwd / "raven.json"]
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return {}

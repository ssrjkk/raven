"""The coding agent's view of the one workspace root — containment here is the workspace alone."""

from __future__ import annotations

from pathlib import Path

from raven.core.workspace import (
    get_workspace_root,
    reset_workspace_root,
    set_workspace_root,
    workspace_root,
)

__all__ = [
    "confine",
    "get_workspace_root",
    "reset_workspace_root",
    "set_workspace_root",
    "workspace_root",
]


def confine(path: str) -> Path:
    """Resolve a tool path inside the workspace; relative names are taken from its root."""
    ws = workspace_root()
    p = Path(path).expanduser()
    p = p.resolve() if p.is_absolute() else (ws / p).resolve()
    try:
        p.relative_to(ws)
    except ValueError as exc:
        msg = f"Path {path} is outside workspace {ws}"
        raise PermissionError(msg) from exc
    return p

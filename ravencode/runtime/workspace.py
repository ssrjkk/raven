from __future__ import annotations

import contextvars
import os
from pathlib import Path

_workspace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "raven_workspace_var", default=None
)


def set_workspace_root(root: str | Path | None) -> None:
    _workspace_var.set(str(root) if root is not None else None)


def get_workspace_root() -> str | None:
    return _workspace_var.get()


def _get_workspace() -> Path:
    override = _workspace_var.get()
    root = override if override is not None else os.environ.get("RAVEN_WORKSPACE", "workspace")
    return Path(root).expanduser().resolve()


def confine(path: str) -> Path:
    ws = _get_workspace()
    p = Path(path)
    if p.is_absolute():
        p = p.expanduser().resolve()
    else:
        p = (ws / p).resolve()
    try:
        p.relative_to(ws)
    except ValueError as exc:
        msg = f"Path {path} is outside workspace {ws}"
        raise PermissionError(msg) from exc
    return p

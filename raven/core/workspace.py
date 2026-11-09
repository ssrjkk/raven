"""The one workspace root, so the layer that confines a path and the layer that checks it agree."""

from __future__ import annotations

import contextvars
import os
import tempfile
from pathlib import Path

_override: contextvars.ContextVar[str | None] = contextvars.ContextVar("raven_workspace_root", default=None)


def set_workspace_root(root: str | os.PathLike[str] | None) -> contextvars.Token[str | None]:
    """Pin the root for this context and return the token that puts the previous one back."""
    return _override.set(str(root) if root else None)


def reset_workspace_root(token: contextvars.Token[str | None]) -> None:
    _override.reset(token)


def get_workspace_root() -> str | None:
    return _override.get()


def _anchor(value: str | os.PathLike[str]) -> Path:
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()


def workspace_root() -> Path:
    """The directory every file, git, OCR and exec path is confined to.

    Precedence: the root the process was given, then RAVEN_WORKSPACE, then WORKSPACE_PATH,
    then the working directory the process was started in.
    """
    pinned = _override.get()
    if pinned:
        return _anchor(pinned)
    env = os.environ.get("RAVEN_WORKSPACE")
    if env and env.strip():
        return _anchor(env)
    from raven.core.config import settings

    if settings.workspace_path.strip():
        return _anchor(settings.workspace_path)
    return Path.cwd().resolve()


def workspace_source() -> str:
    """Which setting decided the root, so `raven doctor` can name it."""
    if _override.get():
        return "the root this process was given"
    env = os.environ.get("RAVEN_WORKSPACE")
    if env and env.strip():
        return "RAVEN_WORKSPACE"
    from raven.core.config import settings

    if settings.workspace_path.strip():
        return "WORKSPACE_PATH"
    return "the working directory"


def allowed_roots() -> tuple[Path, ...]:
    """Directories a path argument may resolve into: the workspace and the system temp directory."""
    return (workspace_root(), _anchor(tempfile.gettempdir()))


def resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p.resolve() if p.is_absolute() else (workspace_root() / p).resolve()


def is_within(path: str) -> bool:
    p = resolve(path)
    return any(p == root or root in p.parents for root in allowed_roots())


def confine(path: str) -> Path:
    if is_within(path):
        return resolve(path)
    roots = " or ".join(str(root) for root in allowed_roots())
    msg = f"Access denied: {path} (outside {roots})"
    raise PermissionError(msg)

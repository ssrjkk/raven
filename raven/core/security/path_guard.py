from __future__ import annotations

import os
from pathlib import Path

__all__ = ["confine_path"]


def confine_path(path: str, base: Path) -> Path:
    root = os.path.abspath(str(base))  # noqa: PTH100
    resolved = os.path.abspath(os.path.normpath(os.path.expanduser(path)))  # noqa: PTH100, PTH111
    if resolved != root and not resolved.startswith(root + os.sep):
        msg = f"Access denied: path outside {base}: {resolved}"
        raise PermissionError(msg)
    return Path(resolved)

from __future__ import annotations

import os
from pathlib import Path

from raven.core.security.secret_paths import credential_reason

__all__ = ["confine_path"]


def confine_path(path: str, base: Path) -> Path:
    # realpath resolves symlinks so a link inside ``base`` pointing outside
    # (e.g. ``base/link -> /etc``) can't escape the workspace boundary.
    root = os.path.realpath(os.path.abspath(str(base)))  # noqa: PTH100
    resolved = os.path.realpath(os.path.abspath(os.path.expanduser(path)))  # noqa: PTH100, PTH111
    if resolved != root and not resolved.startswith(root + os.sep):
        msg = f"Access denied: path outside {base}: {resolved}"
        raise PermissionError(msg)
    reason = credential_reason(Path(resolved), Path(root))
    if reason is not None:
        msg = f"Access denied: {path} {reason}. Credentials stay out of what the model can read."
        raise PermissionError(msg)
    return Path(resolved)

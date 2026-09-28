"""Single source of truth for the package version.

Resolved from the source checkout's ``pyproject.toml`` when present (so a repo clone
always reports its own version), otherwise from the installed distribution metadata.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from pathlib import Path

DIST_NAME = "raven-agent"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_VERSION_RE = re.compile(r'^version = "([^"]+)"', re.MULTILINE)


def _version_from_pyproject() -> str | None:
    pyproject = _PROJECT_ROOT / "pyproject.toml"
    try:
        match = _VERSION_RE.search(pyproject.read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1) if match else None


def resolve_version() -> str:
    """Version of the code being executed (checkout first, then installed metadata)."""
    from_source = _version_from_pyproject()
    if from_source:
        return from_source
    try:
        return _dist_version(DIST_NAME)
    except PackageNotFoundError:
        return "0.0.0"


__version__ = resolve_version()

"""Workspace file traversal.

``Path.rglob("*")`` stats every entry it walks, so a workspace holding
``node_modules`` or ``.git`` spends minutes producing paths that callers then
throw away. ``iter_files`` prunes those trees during the walk instead.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

EXCLUDED_DIR_NAMES: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".eggs",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "site-packages",
    "node_modules",
    "bower_components",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".parcel-cache",
    ".terraform",
    "coverage",
    "allure-results",
    "allure-report",
    ".verdent",
})


def iter_files(root: Path) -> Iterator[Path]:
    """Yield files under ``root``, skipping dependency, build, cache and VCS trees."""
    for current, dir_names, file_names in os.walk(root, followlinks=False):
        dir_names[:] = [name for name in dir_names if name not in EXCLUDED_DIR_NAMES]
        base = Path(current)
        for name in file_names:
            yield base / name

"""Containment for the coding-agent tool layer: ravencode confine() to the one workspace root.

CodeQL flags `Path(path)` in ravencode/runtime/workspace.py as py/path-injection. The path is
resolved before it is compared with the root, so these tests pin the escapes a raw prefix check
would let through: parent traversal written inside the root, and a symlink pointing out of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ravencode.runtime.workspace import confine, reset_workspace_root, set_workspace_root


@pytest.fixture
def ws(tmp_path: Path):
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "notes.md").write_text("hello", encoding="utf-8")
    token = set_workspace_root(root)
    try:
        yield root
    finally:
        reset_workspace_root(token)


def test_relative_name_is_taken_from_the_root(ws: Path) -> None:
    assert confine("notes.md") == (ws / "notes.md").resolve()


def test_traversal_that_stays_inside_the_root_is_allowed(ws: Path) -> None:
    assert confine("sub/../notes.md") == (ws / "notes.md").resolve()
    assert confine(str(ws / "sub" / ".." / "notes.md")) == (ws / "notes.md").resolve()


def test_absolute_inside_the_root_is_allowed(ws: Path) -> None:
    target = ws / "sub" / "file.txt"
    assert confine(str(target)) == target.resolve()


def test_absolute_outside_the_root_is_denied(ws: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(PermissionError, match="outside workspace"):
        confine(str(outside / "secret.txt"))


def test_parent_traversal_out_of_the_root_is_denied(ws: Path) -> None:
    with pytest.raises(PermissionError, match="outside workspace"):
        confine("../secret.txt")
    with pytest.raises(PermissionError, match="outside workspace"):
        confine("sub/../../escape/secret.txt")
    # The string begins with the root and still leaves it; only resolve() catches this one.
    with pytest.raises(PermissionError, match="outside workspace"):
        confine(str(ws / "sub" / ".." / ".." / "escape" / "secret.txt"))


def test_symlink_out_of_the_root_is_denied(ws: Path, tmp_path: Path) -> None:
    real_outside = tmp_path / "real_outside"
    real_outside.mkdir()
    link = ws / "link"
    try:
        link.symlink_to(real_outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(PermissionError, match="outside workspace"):
        confine(str(link / "secret.txt"))

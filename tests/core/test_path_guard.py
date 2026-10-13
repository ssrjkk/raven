from __future__ import annotations

import os
from pathlib import Path

import pytest

from raven.core.security.path_guard import confine_path


def test_confine_allows_file_inside_base(tmp_path: Path) -> None:
    inner = tmp_path / "sub" / "file.txt"
    inner.parent.mkdir()
    inner.write_text("x", encoding="utf-8")
    result = confine_path(str(inner), tmp_path)
    assert result == inner.resolve()


def test_confine_allows_base_itself(tmp_path: Path) -> None:
    assert confine_path(str(tmp_path), tmp_path) == tmp_path.resolve()


def test_confine_allows_relative_inside(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        result = confine_path("a.txt", tmp_path)
        assert result.name == "a.txt"
    finally:
        os.chdir(cwd)


def test_confine_denies_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    with pytest.raises(PermissionError, match="Access denied"):
        confine_path(str(outside), tmp_path)


def test_confine_denies_parent_traversal(tmp_path: Path) -> None:
    target = str(tmp_path / ".." / "secret")
    with pytest.raises(PermissionError):
        confine_path(target, tmp_path)


def test_confine_denies_symlink_escape(tmp_path: Path) -> None:
    real_outside = tmp_path.parent / "real_outside"
    real_outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(real_outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(PermissionError):
        confine_path(str(link / "file.txt"), tmp_path)


def test_confine_expands_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(home)))
    (home / "notes.txt").write_text("x", encoding="utf-8")
    result = confine_path("~/notes.txt", home)
    assert result.name == "notes.txt"

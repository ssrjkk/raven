from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from ravencode.runtime.diff import apply_patch, compute_patch, smart_edit


@pytest.fixture(autouse=True)
def _set_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    from ravencode.runtime import workspace as _ws

    token = _ws._workspace_var.set(str(tmp_path))
    yield
    _ws._workspace_var.reset(token)


class TestComputePatch:
    def test_returns_unified_diff(self):
        diff = compute_patch("hello\nworld\n", "hello\nuniverse\n", "test.txt")
        assert diff.startswith("--- test.txt")
        assert "hello" in diff
        assert "-world" in diff
        assert "+universe" in diff

    def test_identical_returns_empty(self):
        diff = compute_patch("same\n", "same\n")
        assert diff == ""

    def test_defaults_to_file(self):
        diff = compute_patch("a\n", "b\n")
        assert "--- file" in diff


class TestApplyPatch:
    def test_apply_simple_patch(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("line1\nline2\nline3\n")
        diff = compute_patch("line1\nline2\nline3\n", "line1\nmodified\nline3\n", str(f))
        result = apply_patch(str(f), diff)
        assert result.startswith("[ok]")
        assert f.read_text(encoding="utf-8") == "line1\nmodified\nline3\n"

    def test_file_not_found(self, tmp_path: Path):
        result = apply_patch(str(tmp_path / "missing.txt"), "--- \n@@ -1 +1 @@\n-old\n+new\n")
        assert "file not found" in result

    def test_invalid_diff_no_hunks(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("content\n")
        result = apply_patch(str(f), "this is not a diff")
        assert "no valid hunks" in result


class TestSmartEdit:
    def test_replace_text(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("hello world\n")
        result = smart_edit(str(f), old_text="world", new_text="there")
        assert result.startswith("[ok]")
        assert f.read_text(encoding="utf-8") == "hello there\n"

    def test_old_text_not_found(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("hello\n")
        result = smart_edit(str(f), old_text="nonexistent", new_text="x")
        assert "old_text not found" in result

    def test_ambiguous_replace(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("a\na\na\n")
        result = smart_edit(str(f), old_text="a", new_text="b")
        assert "occurrences" in result

    def test_insert_after(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("start\nend\n")
        result = smart_edit(str(f), insert_after="start", new_text="\nmiddle")
        assert result.startswith("[ok]")
        assert f.read_text(encoding="utf-8") == "start\nmiddle\nend\n"

    def test_insert_before(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("start\nend\n")
        result = smart_edit(str(f), insert_before="end", new_text="middle\n")
        assert result.startswith("[ok]")
        assert f.read_text(encoding="utf-8") == "start\nmiddle\nend\n"

    def test_append(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("line1\n")
        result = smart_edit(str(f), append=True, new_text="line2\n")
        assert result.startswith("[ok]")
        assert f.read_text(encoding="utf-8") == "line1\nline2\n"

    def test_file_not_found(self, tmp_path: Path):
        result = smart_edit(str(tmp_path / "missing.txt"), old_text="a", new_text="b")
        assert "file not found" in result

    def test_no_args(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("content\n")
        result = smart_edit(str(f))
        assert "provide" in result

from __future__ import annotations

import tempfile
from pathlib import Path

from ravencode.runtime.diff import apply_patch, compute_patch, smart_edit


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
    def test_apply_simple_patch(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("line1\nline2\nline3\n")
            path = f.name
        try:
            diff = compute_patch("line1\nline2\nline3\n", "line1\nmodified\nline3\n", path)
            result = apply_patch(path, diff)
            assert result.startswith("[ok]")
            content = Path(path).read_text(encoding="utf-8")
            assert content == "line1\nmodified\nline3\n"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_file_not_found(self):
        result = apply_patch("/nonexistent/path.txt", "--- \n@@ -1 +1 @@\n-old\n+new\n")
        assert "file not found" in result

    def test_invalid_diff_no_hunks(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("content\n")
            path = f.name
        try:
            result = apply_patch(path, "this is not a diff")
            assert "no valid hunks" in result
        finally:
            Path(path).unlink(missing_ok=True)


class TestSmartEdit:
    def test_replace_text(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("hello world\n")
            path = f.name
        try:
            result = smart_edit(path, old_text="world", new_text="there")
            assert result.startswith("[ok]")
            assert Path(path).read_text(encoding="utf-8") == "hello there\n"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_old_text_not_found(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("hello\n")
            path = f.name
        try:
            result = smart_edit(path, old_text="nonexistent", new_text="x")
            assert "old_text not found" in result
        finally:
            Path(path).unlink(missing_ok=True)

    def test_ambiguous_replace(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("a\na\na\n")
            path = f.name
        try:
            result = smart_edit(path, old_text="a", new_text="b")
            assert "occurrences" in result
        finally:
            Path(path).unlink(missing_ok=True)

    def test_insert_after(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("start\nend\n")
            path = f.name
        try:
            result = smart_edit(path, insert_after="start", new_text="\nmiddle")
            assert result.startswith("[ok]")
            assert Path(path).read_text(encoding="utf-8") == "start\nmiddle\nend\n"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_insert_before(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("start\nend\n")
            path = f.name
        try:
            result = smart_edit(path, insert_before="end", new_text="middle\n")
            assert result.startswith("[ok]")
            assert Path(path).read_text(encoding="utf-8") == "start\nmiddle\nend\n"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_append(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("line1\n")
            path = f.name
        try:
            result = smart_edit(path, append=True, new_text="line2\n")
            assert result.startswith("[ok]")
            assert Path(path).read_text(encoding="utf-8") == "line1\nline2\n"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_file_not_found(self):
        result = smart_edit("/nonexistent/path.txt", old_text="a", new_text="b")
        assert "file not found" in result

    def test_no_args(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("content\n")
            path = f.name
        try:
            result = smart_edit(path)
            assert "provide" in result
        finally:
            Path(path).unlink(missing_ok=True)

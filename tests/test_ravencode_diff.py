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


class TestApplyPatchShapes:
    """Every case here is a shape the old loop got wrong or refused."""

    def _file(self, tmp_path: Path, name: str, content: str | bytes) -> Path:
        p = tmp_path / name
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            with p.open("w", encoding="utf-8", newline="") as f:
                f.write(content)
        return p

    def test_insertion_only_hunk_is_applied(self, tmp_path: Path):
        p = self._file(tmp_path, "a.txt", "one\ntwo\n")
        assert apply_patch(str(p), "@@ -1,0 +2,1 @@\n+inserted\n").startswith("[ok]")
        assert p.read_text(encoding="utf-8") == "one\ninserted\ntwo\n"

    def test_insertion_at_the_very_start(self, tmp_path: Path):
        p = self._file(tmp_path, "a.txt", "one\n")
        assert apply_patch(str(p), "@@ -0,0 +1,1 @@\n+before\n").startswith("[ok]")
        assert p.read_text(encoding="utf-8") == "before\none\n"

    def test_hunk_declaring_more_lines_than_it_carries_is_refused(self, tmp_path: Path):
        p = self._file(tmp_path, "a.txt", "one\n")
        result = apply_patch(str(p), "@@ -1,1 +1,4 @@\n-one\n+one\n")
        assert "declares -1 +4" in result
        assert p.read_text(encoding="utf-8") == "one\n"

    def test_hunks_apply_in_any_order(self, tmp_path: Path):
        src = "a\nb\nc\nd\ne\nf\ng\nh\n"
        wanted = "A\nb\nc\nd\ne\nf\nG1\nG2\nh\n"
        ascending = "@@ -1,1 +1,1 @@\n-a\n+A\n@@ -7,1 +7,2 @@\n-g\n+G1\n+G2\n"
        descending = "@@ -7,1 +7,2 @@\n-g\n+G1\n+G2\n@@ -1,1 +1,1 @@\n-a\n+A\n"
        outputs = []
        for diff in (ascending, descending):
            p = self._file(tmp_path, "ord.txt", src)
            assert apply_patch(str(p), diff).startswith("[ok]")
            outputs.append(p.read_text(encoding="utf-8"))
        assert outputs == [wanted, wanted]

    def test_crlf_file_keeps_crlf(self, tmp_path: Path):
        p = self._file(tmp_path, "win.txt", b"one\r\ntwo\r\nthree\r\n")
        assert apply_patch(str(p), "@@ -1,2 +1,2 @@\n one\n-two\n+2\n").startswith("[ok]")
        assert p.read_bytes() == b"one\r\n2\r\nthree\r\n"

    def test_lf_file_is_not_rewritten_with_host_endings(self, tmp_path: Path):
        p = self._file(tmp_path, "unix.txt", b"one\ntwo\n")
        assert apply_patch(str(p), "@@ -1,2 +1,2 @@\n one\n-two\n+2\n").startswith("[ok]")
        assert p.read_bytes() == b"one\n2\n"

    def test_missing_final_newline_survives_a_patch(self, tmp_path: Path):
        p = self._file(tmp_path, "tail.txt", b"one\ntwo")
        assert apply_patch(str(p), "@@ -1,2 +1,2 @@\n one\n-two\n+2\n").startswith("[ok]")
        assert p.read_bytes() == b"one\n2"

    def test_apply_patch_records_an_undo_entry(self, tmp_path: Path):
        from ravencode.runtime.undo import get_undo_manager

        p = self._file(tmp_path, "u.txt", "x\ny\n")
        before = len(get_undo_manager()._undo_stack)
        assert apply_patch(str(p), "@@ -1,1 +1,1 @@\n-x\n+z\n").startswith("[ok]")
        assert len(get_undo_manager()._undo_stack) == before + 1

    def test_a_rejected_patch_leaves_the_file_and_no_temporary(self, tmp_path: Path):
        p = self._file(tmp_path, "keep.txt", "one\ntwo\n")
        assert "context mismatch" in apply_patch(str(p), "@@ -1,1 +1,1 @@\n-nope\n+yes\n")
        assert p.read_text(encoding="utf-8") == "one\ntwo\n"
        assert list(p.parent.glob("*.tmp")) == []

    def test_binary_target_reports_inst_of_raising(self, tmp_path: Path):
        p = self._file(tmp_path, "b.bin", b"\xff\xfe\x00binary")
        assert apply_patch(str(p), "@@ -1,1 +1,1 @@\n-a\n+b\n").startswith("[error] cannot read")

    def test_multi_file_diff_is_refused(self, tmp_path: Path):
        p = self._file(tmp_path, "m.txt", "one\n")
        diff = "--- a/m.txt\n+++ b/m.txt\n@@ -1,1 +1,1 @@\n-one\n+ONE\n--- a/n.txt\n+++ b/n.txt\n@@ -1,1 +1,1 @@\n-x\n+y\n"
        assert "multi-file" in apply_patch(str(p), diff)
        assert p.read_text(encoding="utf-8") == "one\n"

    def test_removed_line_starting_with_dashes_is_content_not_a_header(self, tmp_path: Path):
        p = self._file(tmp_path, "sql.txt", "-- comment\nnext\n")
        result = apply_patch(str(p), "@@ -1,2 +1,2 @@\n--- comment\n+-- comment\n next\n")
        assert result.startswith("[ok]"), result
        assert p.read_text(encoding="utf-8") == "-- comment\nnext\n"

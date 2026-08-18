from __future__ import annotations

from unittest.mock import AsyncMock

from ravencode.runtime.diff import (
    apply_patch,
    compute_patch,
    patch_file,
    smart_edit,
    smart_edit_tool,
)


class TestParseUnifiedDiff:
    def test_parses_hunk(self) -> None:
        from ravencode.runtime.diff import _parse_unified_diff

        diff = "@@ -1,3 +1,2 @@\n- a\n+ b\n c\n"
        hunks = _parse_unified_diff(diff)
        assert len(hunks) == 1
        h = hunks[0]
        assert h["old_start"] == 1
        assert h["old_count"] == 3
        assert h["new_start"] == 1
        assert h["new_count"] == 2
        assert h["lines"] == ["- a\n", "+ b\n", " c\n"]

    def test_hunk_without_counts(self) -> None:
        from ravencode.runtime.diff import _parse_unified_diff

        hunks = _parse_unified_diff("@@ -5 +6 @@\nx\n")
        h = hunks[0]
        assert h["old_start"] == 5
        assert h["old_count"] == 1
        assert h["new_start"] == 6
        assert h["new_count"] == 1

    def test_multiple_hunks(self) -> None:
        from ravencode.runtime.diff import _parse_unified_diff

        hunks = _parse_unified_diff("@@ -1 +1 @@\na\n@@ -10 +10 @@\nb\n")
        assert len(hunks) == 2

    def test_no_hunk(self) -> None:
        from ravencode.runtime.diff import _parse_unified_diff

        assert _parse_unified_diff("just text") == []


class TestApplyPatch:
    def test_file_not_found(self, tmp_path) -> None:
        result = apply_patch(str(tmp_path / "missing.txt"), "@@ -1 +1 @@\n")
        assert result == "[error] file not found: " + str(tmp_path / "missing.txt")

    def test_no_valid_hunks(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x\n")
        assert apply_patch(str(f), "no hunks here") == "[error] no valid hunks in diff"

    def test_success(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("one\ntwo\n")
        result = apply_patch(str(f), "@@ -1,2 +1,2 @@\n one\n-two\n+three\n")
        assert result == "[ok] applied patch to " + str(f) + " (1 hunks)"
        assert f.read_text(encoding="utf-8") == "one\nthree\n"

    def test_context_mismatch(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("different\n")
        result = apply_patch(str(f), "@@ -1 +1 @@\n-expected\n+actual\n")
        assert result.startswith("[error] context mismatch")

    def test_no_change_hunk(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x\n")
        result = apply_patch(str(f), "@@ -1 +1 @@\n+a\n")
        assert result == "[error] no valid hunks in diff"
        assert f.read_text(encoding="utf-8") == "x\n"

    def test_skip_empty_line_in_hunk(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x\n")
        result = apply_patch(str(f), "@@ -1 +1 @@\n-x\n+\n")
        assert f.read_text(encoding="utf-8") == "\n"
        assert result.startswith("[ok]")

    def test_multiple_hunks_offset(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("l1\nl2\nl3\nl4\n")
        diff = "@@ -1,2 +1,2 @@\n-l1\n+l1a\n l2\n@@ -3,2 +3,2 @@\n l3\n-l4\n+l4a\n"
        result = apply_patch(str(f), diff)
        assert result.startswith("[ok]")
        assert f.read_text(encoding="utf-8") == "l1a\nl2\nl3\nl4a\n"


class TestSmartEdit:
    def test_file_not_found(self, tmp_path) -> None:
        assert smart_edit(str(tmp_path / "x.txt"), old_text="a", new_text="b") == "[error] file not found: " + str(
            tmp_path / "x.txt"
        )

    def test_old_text_not_found(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hello")
        assert smart_edit(str(f), old_text="bye", new_text="hi") == "[error] old_text not found in " + str(f)

    def test_multiple_occurrences(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("xx xx")
        assert smart_edit(str(f), old_text="xx", new_text="yy") == "[error] 2 occurrences — provide more context"

    def test_replace_success(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hello world")
        result = smart_edit(str(f), old_text="world", new_text="raven")
        assert result == "[ok] replaced text in " + str(f)
        assert f.read_text(encoding="utf-8") == "hello raven"

    def test_insert_after(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("ab")
        result = smart_edit(str(f), insert_after="a", new_text="X")
        assert result == "[ok] inserted after in " + str(f)
        assert f.read_text(encoding="utf-8") == "aXb"

    def test_insert_after_not_found(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("ab")
        assert smart_edit(str(f), insert_after="z", new_text="X") == "[error] insert_after not found in " + str(f)

    def test_insert_before(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("ab")
        result = smart_edit(str(f), insert_before="b", new_text="Y")
        assert result == "[ok] inserted before in " + str(f)
        assert f.read_text(encoding="utf-8") == "aYb"

    def test_insert_before_not_found(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("ab")
        assert smart_edit(str(f), insert_before="z", new_text="X") == "[error] insert_before not found in " + str(f)

    def test_append(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("ab")
        result = smart_edit(str(f), append=True, new_text="CD")
        assert result == "[ok] appended to " + str(f)
        assert f.read_text(encoding="utf-8") == "abCD"

    def test_no_mode(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("ab")
        assert smart_edit(str(f)) == "[error] provide old_text+new_text or insert_after/new_text+insert_before or append"


class TestComputePatch:
    def test_produces_unified_diff(self) -> None:
        patch = compute_patch("a\nb\n", "a\nc\n", "f.txt")
        assert "+++ f.txt" in patch
        assert "-b" in patch
        assert "+c" in patch


class TestWrappers:
    async def test_patch_file(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x\n")
        result = await patch_file(str(f), "@@ -1 +1 @@\n-x\n+y\n")
        assert result.startswith("[ok]")
        assert f.read_text(encoding="utf-8") == "y\n"

    async def test_smart_edit_tool(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("ab")
        result = await smart_edit_tool(str(f), old_text="a", new_text="z")
        assert result == "[ok] replaced text in " + str(f)


class TestAsyncHelpers:
    async def test_patch_file_wrapper_uses_apply(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_apply(path: str, diff_text: str) -> str:
            calls.append((path, diff_text))
            return "[ok] x"

        with __import__("unittest.mock").mock.patch("ravencode.runtime.diff.apply_patch", new=fake_apply):
            assert await patch_file("some/path.txt", "diff") == "[ok] x"
        assert calls == [("some/path.txt", "diff")]

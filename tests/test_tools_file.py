from __future__ import annotations

import os
import pathlib
from collections.abc import Generator
from pathlib import Path

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.file import (
    _confine,
    _confine_fd,
    _workspace,
    file_append,
    file_delete,
    file_edit,
    file_list,
    file_read,
    file_read_relevant,
    file_write,
    register_file_tools,
)

_DOC = "\U0001f4c4"
_DIR = "\U0001f4c1"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Generator[Path, None, None]:
    old = os.environ.get("RAVEN_WORKSPACE")
    os.environ["RAVEN_WORKSPACE"] = str(tmp_path)
    yield tmp_path
    if old:
        os.environ["RAVEN_WORKSPACE"] = old
    else:
        os.environ.pop("RAVEN_WORKSPACE", None)


class TestWorkspace:
    def test_default_workspace(self, monkeypatch) -> None:
        monkeypatch.delenv("RAVEN_WORKSPACE", raising=False)
        assert _workspace() == Path("data").resolve()

    def test_workspace_from_env(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
        assert _workspace() == tmp_path.resolve()


class TestConfine:
    def test_ok(self, tmp_workspace: Path) -> None:
        p = _confine(str(tmp_workspace / "a" / "b.txt"))
        assert p == (tmp_workspace / "a" / "b.txt").resolve()

    def test_outside_raises(self, tmp_workspace: Path) -> None:
        with pytest.raises(PermissionError, match="Access denied"):
            _confine(str(tmp_workspace.parent / "secret.txt"))

    def test_symlink_in_path_raises(self, tmp_workspace: Path, monkeypatch) -> None:
        target = tmp_workspace.resolve() / "sub"
        monkeypatch.setattr(pathlib.Path, "is_symlink", lambda self: self == target)
        with pytest.raises(PermissionError, match="Symlink detected in path"):
            _confine(str(target / "file.txt"))


class TestConfineFd:
    def test_creates_parent_dirs(self, tmp_workspace: Path, monkeypatch) -> None:
        captured: list[str] = []

        def fake_open(path: str, flags: int, mode: int = 0o644) -> int:
            captured.append(path)
            return 99

        monkeypatch.setattr("raven.tools.file.os.open", fake_open)
        fd = _confine_fd(str(tmp_workspace / "nested" / "file.txt"), os.O_WRONLY)
        assert fd == 99
        assert (tmp_workspace / "nested").is_dir()
        assert captured[0] == str((tmp_workspace / "nested" / "file.txt").resolve())

    def test_symlink_errno_raises_permission(self, tmp_workspace: Path, monkeypatch) -> None:
        def fake_open(path: str, flags: int, mode: int = 0o644) -> int:
            raise OSError(34, "symlink-ish")

        monkeypatch.setattr("raven.tools.file.os.open", fake_open)
        with pytest.raises(PermissionError, match="Symlink detected"):
            _confine_fd(str(tmp_workspace / "x.txt"), os.O_WRONLY)

    def test_os_error_reraised(self, tmp_workspace: Path, monkeypatch) -> None:
        def fake_open(path: str, flags: int, mode: int = 0o644) -> int:
            raise OSError(13, "permission denied")

        monkeypatch.setattr("raven.tools.file.os.open", fake_open)
        with pytest.raises(OSError):
            _confine_fd(str(tmp_workspace / "x.txt"), os.O_WRONLY)

    def test_outside_raises(self, tmp_workspace: Path) -> None:
        with pytest.raises(PermissionError):
            _confine_fd(str(tmp_workspace.parent / "x.txt"), os.O_WRONLY)


class TestFileRead:
    async def test_read_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "hello.txt"
        f.write_text("Hello, World!", encoding="utf-8")
        result = await file_read(str(f))
        assert "Hello, World!" in result

    async def test_read_missing(self, tmp_workspace: Path) -> None:
        with pytest.raises(FileNotFoundError):
            await file_read(str(tmp_workspace / "nope.txt"))

    async def test_read_outside_workspace(self, tmp_workspace: Path) -> None:
        outside = tmp_workspace.parent / "outside.txt"
        outside.write_text("hack", encoding="utf-8")
        try:
            with pytest.raises(PermissionError):
                await file_read(str(outside))
        finally:
            outside.unlink(missing_ok=True)

    async def test_read_truncated(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "big.txt"
        f.write_text("x" * 100, encoding="utf-8")
        result = await file_read(str(f), max_size=10)
        assert result == "x" * 10 + "\n... (truncated, 100 total bytes)"

    async def test_read_zero_max_size(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "big.txt"
        f.write_text("x" * 100, encoding="utf-8")
        result = await file_read(str(f), max_size=0)
        assert result == "\n... (truncated, 100 total bytes)"


class TestFileWrite:
    async def test_write_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "new.txt"
        result = await file_write(str(f), "test content")
        assert "Written" in result
        assert f.read_text(encoding="utf-8") == "test content"

    async def test_write_creates_parent_dirs(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "deep" / "nested" / "new.txt"
        result = await file_write(str(f), "data")
        assert "Written" in result
        assert f.read_text(encoding="utf-8") == "data"

    async def test_write_outside_workspace(self, tmp_workspace: Path) -> None:
        outside = tmp_workspace.parent / "w_out.txt"
        with pytest.raises(PermissionError):
            await file_write(str(outside), "data")

    async def test_append_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "append.txt"
        f.write_text("base", encoding="utf-8")
        result = await file_append(str(f), "+more")
        assert "Appended" in result
        assert f.read_text(encoding="utf-8") == "base+more"

    async def test_append_creates_file(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "fresh.txt"
        await file_append(str(f), "first")
        assert f.read_text(encoding="utf-8") == "first"


class TestFileEdit:
    async def test_edit_ok(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "edit.txt"
        f.write_text("Hello World World", encoding="utf-8")
        result = await file_edit(str(f), "World", "Raven")
        assert f.read_text(encoding="utf-8") == "Hello Raven World"
        assert "Applied edit" in result

    async def test_edit_old_string_not_found(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "edit.txt"
        f.write_text("alpha beta", encoding="utf-8")
        result = await file_edit(str(f), "gamma", "delta")
        assert "[error] old_string not found" in result


class TestFileList:
    async def test_list_ok(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "a.py").write_text("x", encoding="utf-8")
        (tmp_workspace / "b.py").write_text("", encoding="utf-8")
        result = await file_list(str(tmp_workspace), "*.py")
        assert f"{_DOC} a.py  (1 bytes)" in result
        assert f"{_DOC} b.py" in result
        assert "  (0 bytes)" not in result

    async def test_list_directory_entry(self, tmp_workspace: Path) -> None:
        (tmp_workspace / "folder").mkdir()
        result = await file_list(str(tmp_workspace), "*")
        assert f"{_DIR} folder" in result

    async def test_list_empty(self, tmp_workspace: Path) -> None:
        result = await file_list(str(tmp_workspace))
        assert "(empty)" in result

    async def test_list_not_found(self, tmp_workspace: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Directory not found"):
            await file_list(str(tmp_workspace / "nope"))

    async def test_list_default_path(self, tmp_workspace: Path, monkeypatch) -> None:
        (tmp_workspace / "def.txt").write_text("x", encoding="utf-8")
        monkeypatch.chdir(tmp_workspace)
        result = await file_list()
        assert "def.txt" in result

    async def test_list_truncated_too_many(self, tmp_workspace: Path, monkeypatch) -> None:
        monkeypatch.setattr("raven.tools.file._MAX_LIST_ITEMS", 3)
        for i in range(5):
            (tmp_workspace / f"f{i}.txt").write_text("x", encoding="utf-8")
        result = await file_list(str(tmp_workspace), "*.txt")
        assert "... (truncated, too many files)" in result
        assert result.count("\n") == 3

    async def test_list_depth_limit(self, tmp_workspace: Path) -> None:
        cur = tmp_workspace
        for _ in range(12):
            cur = cur / "d"
            cur.mkdir()
        result = await file_list(str(tmp_workspace), "**/*")
        assert "... (truncated, depth limit reached)" in result

    async def test_list_item_outside_base_skips_depth(self, tmp_workspace: Path, monkeypatch) -> None:
        outside = tmp_workspace.parent / "outside-item.txt"
        outside.write_text("x", encoding="utf-8")
        monkeypatch.setattr(pathlib.Path, "glob", lambda self, pat: [outside])
        try:
            result = await file_list(str(tmp_workspace))
            assert "outside-item.txt" in result
        finally:
            outside.unlink(missing_ok=True)


class TestFileDelete:
    async def test_delete_file(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "del.txt"
        f.write_text("x", encoding="utf-8")
        result = await file_delete(str(f))
        assert "Deleted" in result
        assert not f.exists()

    async def test_delete_directory(self, tmp_workspace: Path) -> None:
        d = tmp_workspace / "dir"
        d.mkdir()
        (d / "inner.txt").write_text("x", encoding="utf-8")
        result = await file_delete(str(d))
        assert "Deleted directory" in result
        assert not d.exists()

    async def test_delete_not_found(self, tmp_workspace: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Not found"):
            await file_delete(str(tmp_workspace / "ghost.txt"))


class TestReadRelevant:
    async def test_small_file_returned_whole(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "small.py"
        f.write_text("import os\n\nVALUE = 1\n", encoding="utf-8")
        result = await file_read_relevant(str(f), query="anything")
        assert result == "import os\n\nVALUE = 1\n"

    async def test_python_prunes_to_matching_blocks(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "big.py"
        source = "\n".join(
            [
                "import os\nimport sys\n\n",
                "def _helper():\n    return 1\n\n",
                "def heavy_unrelated():\n    return 'x' * 1000\n\n" * 40,
                "class Calculator:\n    def add(self, a, b):\n        return a + b\n",
            ]
        )
        f.write_text(source, encoding="utf-8")
        result = await file_read_relevant(str(f), query="Calculator", max_lines=15)
        assert "import os" in result
        assert "class Calculator" in result
        assert "heavy_unrelated" not in result
        assert "pruned" in result
        assert len(result.splitlines()) <= 16

    async def test_python_no_match_returns_notice(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "big2.py"
        f.write_text("def alpha():\n    return 1\n\ndef beta():\n    return 2\n" * 40, encoding="utf-8")
        result = await file_read_relevant(str(f), query="gamma", max_lines=5)
        assert "No relevant symbols found" in result

    async def test_generic_js_prunes_by_function(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "app.js"
        body = "\n\n".join(
            [f"export function fn_{i}(x) {{\n  return x * {i};\n}}" for i in range(1, 31)]
        )
        f.write_text(body, encoding="utf-8")
        result = await file_read_relevant(str(f), query="fn_7", max_lines=10)
        assert "fn_7" in result
        assert "fn_30" not in result
        assert "pruned" in result

    async def test_python_keeps_decorators(self, tmp_workspace: Path) -> None:
        f = tmp_workspace / "api_big.py"
        source = "\n".join(
            [
                "from fastapi import APIRouter\n\n",
                "router = APIRouter()\n\n",
                "def _helper():\n    return 1\n\n",
                "@router.get('/ping')\nasync def ping():\n    return {'ok': True}\n\n" * 30,
            ]
        )
        f.write_text(source, encoding="utf-8")
        result = await file_read_relevant(str(f), query="ping", max_lines=8)
        assert "@router.get" in result
        assert "async def ping" in result

    async def test_missing_file_raises(self, tmp_workspace: Path) -> None:
        with pytest.raises(OSError):
            await file_read_relevant(str(tmp_workspace / "ghost.py"))


class TestRegisterFileTools:
    def test_registers_tools(self) -> None:
        registry = ToolRegistry()
        register_file_tools(registry)
        assert registry.count == 7
        for name in ("file_read", "file_write", "file_append", "file_edit", "file_list", "file_delete", "file_read_relevant"):
            spec = registry.get(name)
            assert spec is not None
            assert spec.category == "file"

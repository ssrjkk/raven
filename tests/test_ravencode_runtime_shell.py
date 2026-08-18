from __future__ import annotations

from unittest.mock import AsyncMock

from ravencode.runtime.shell import ShellExecutor


class TestShellExecutor:
    async def test_run_with_default_timeout(self, monkeypatch) -> None:
        fake = AsyncMock(return_value="out")
        monkeypatch.setattr("ravencode.runtime.shell.bash_exec", fake)
        result = await ShellExecutor().run("ls")
        assert result == "out"
        fake.assert_awaited_once_with(command="ls", timeout=ShellExecutor.DEFAULT_TIMEOUT)

    async def test_run_with_explicit_timeout(self, monkeypatch) -> None:
        fake = AsyncMock(return_value="out")
        monkeypatch.setattr("ravencode.runtime.shell.bash_exec", fake)
        result = await ShellExecutor().run("ls", timeout=5)
        assert result == "out"
        fake.assert_awaited_once_with(command="ls", timeout=5)

    async def test_read_file(self, monkeypatch) -> None:
        fake = AsyncMock(return_value="content")
        monkeypatch.setattr("ravencode.runtime.shell.read_file", fake)
        assert await ShellExecutor().read_file("a.py") == "content"
        fake.assert_awaited_once_with(path="a.py")

    async def test_write_file(self, monkeypatch) -> None:
        fake = AsyncMock(return_value="ok")
        monkeypatch.setattr("ravencode.runtime.shell.write_file", fake)
        assert await ShellExecutor().write_file("a.py", "body") == "ok"
        fake.assert_awaited_once_with(path="a.py", content="body")

    async def test_edit_file(self, monkeypatch) -> None:
        fake = AsyncMock(return_value="ok")
        monkeypatch.setattr("ravencode.runtime.shell.edit_file", fake)
        assert await ShellExecutor().edit_file("a.py", "old", "new") == "ok"
        fake.assert_awaited_once_with(path="a.py", old_string="old", new_string="new", preview=False)

    async def test_glob_files(self, monkeypatch) -> None:
        fake = AsyncMock(return_value=["a.py"])
        monkeypatch.setattr("ravencode.runtime.shell.glob_files", fake)
        assert await ShellExecutor().glob_files("**/*.py", "src") == ["a.py"]
        fake.assert_awaited_once_with(pattern="**/*.py", path="src")

    async def test_glob_files_default_path(self, monkeypatch) -> None:
        fake = AsyncMock(return_value=[])
        monkeypatch.setattr("ravencode.runtime.shell.glob_files", fake)
        assert await ShellExecutor().glob_files("**/*.py") == []
        fake.assert_awaited_once_with(pattern="**/*.py", path=None)

    async def test_grep_files(self, monkeypatch) -> None:
        fake = AsyncMock(return_value=[{"line": 1}])
        monkeypatch.setattr("ravencode.runtime.shell.grep_files", fake)
        assert await ShellExecutor().grep_files("foo", "*.py", "src") == [{"line": 1}]
        fake.assert_awaited_once_with(pattern="foo", include="*.py", path="src")

    async def test_grep_files_defaults(self, monkeypatch) -> None:
        fake = AsyncMock(return_value=[])
        monkeypatch.setattr("ravencode.runtime.shell.grep_files", fake)
        assert await ShellExecutor().grep_files("foo") == []
        fake.assert_awaited_once_with(pattern="foo", include=None, path=None)

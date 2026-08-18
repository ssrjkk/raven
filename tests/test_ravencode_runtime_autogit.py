from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from ravencode.runtime.autogit import (
    _git,
    _guess_commit_type,
    _summarize_diff,
    auto_commit,
    auto_commit_tool,
)


def _proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


class TestGit:
    async def test_success(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.autogit.asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(b"out"))
        )
        result = await _git("status", "--porcelain")
        assert result == "out"

    async def test_timeout(self, monkeypatch) -> None:
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError())
        monkeypatch.setattr("ravencode.runtime.autogit.asyncio.create_subprocess_exec", AsyncMock(return_value=proc))
        assert await _git("status") == "[timeout]"

    async def test_stderr_appended(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.autogit.asyncio.create_subprocess_exec",
            AsyncMock(return_value=_proc(b"out", b"warn")),
        )
        assert await _git("status") == "out\nwarn"

    async def test_exit_code(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ravencode.runtime.autogit.asyncio.create_subprocess_exec",
            AsyncMock(return_value=_proc(returncode=1)),
        )
        assert await _git("status") == "[exit code: 1]"


class TestGuessCommitType:
    def test_python_with_def(self) -> None:
        assert _guess_commit_type(["a.py"], ["+ def foo()"]) == "feat"

    def test_python_without_def(self) -> None:
        assert _guess_commit_type(["a.py"], ["+ x = 1"]) == "fix"

    def test_ts_with_function(self) -> None:
        assert _guess_commit_type(["a.ts"], ["+ function f()"]) == "feat"

    def test_ts_without_function(self) -> None:
        assert _guess_commit_type(["a.ts"], ["+ const x = 1"]) == "fix"

    def test_docs(self) -> None:
        assert _guess_commit_type(["README.md"], [""]) == "docs"

    def test_config(self) -> None:
        assert _guess_commit_type(["conf.yml"], [""]) == "chore"

    def test_pyi_go_rs(self) -> None:
        assert _guess_commit_type(["a.go"], [""]) == "feat"
        assert _guess_commit_type(["a.rs"], [""]) == "feat"
        assert _guess_commit_type(["a.pyi"], [""]) == "feat"

    def test_unknown(self) -> None:
        assert _guess_commit_type(["file.txt"], [""]) == "chore"

    def test_precedence(self) -> None:
        assert _guess_commit_type(["a.py", "README.md", "b.go"], [""]) == "feat"
        assert _guess_commit_type(["README.md", "conf.yml"], [""]) == "docs"


class TestSummarizeDiff:
    def test_added_lines(self) -> None:
        assert _summarize_diff("+line1\n+line2") == "line1; line2"

    def test_removed_lines(self) -> None:
        assert _summarize_diff("-old1\n-old2") == "old1; old2"

    def test_excludes_headers(self) -> None:
        assert _summarize_diff("--- a/file\n+++ b/file\n+real") == "real"

    def test_max_lines(self) -> None:
        diff = "".join(f"+line{i}\n" for i in range(10))
        assert _summarize_diff(diff, max_lines=3) == "line0; line1; line2"

    def test_no_changes(self) -> None:
        assert _summarize_diff("context only") == "(no meaningful changes)"

    def test_line_truncated(self) -> None:
        assert _summarize_diff("+" + "x" * 200) == "x" * 79


class TestAutoCommit:
    async def test_nothing_to_commit(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.runtime.autogit._git", AsyncMock(return_value=""))
        assert await auto_commit() == "(nothing to commit)"

    async def test_git_error_returned(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.runtime.autogit._git", AsyncMock(return_value="[exit code: 128]"))
        assert await auto_commit() == "[exit code: 128]"

    async def test_no_changed_files(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.runtime.autogit._git", AsyncMock(return_value="  "))
        assert await auto_commit() == "(nothing to commit)"

    async def test_with_message(self, monkeypatch) -> None:
        calls: list[tuple[tuple[str, ...], str | None]] = []
        async def fake_git(*args, cwd=None) -> str:
            calls.append((args, cwd))
            if args[0] == "status":
                return " M src/a.py\n"
            if args[0] == "diff":
                return "+ def foo()\n"
            return ""

        monkeypatch.setattr("ravencode.runtime.autogit._git", fake_git)
        result = await auto_commit(message="custom msg", path="repo")
        assert result == "[ok] committed 1 file(s): custom msg"
        assert ("add", "-A") in [c[0] for c in calls]
        assert ("commit", "-m", "custom msg") in [c[0] for c in calls]

    async def test_generated_message(self, monkeypatch) -> None:
        async def fake_git(*args, cwd=None) -> str:
            if args[0] == "status":
                return " M src/a.py\n M README.md\n"
            if args[0] == "diff":
                return "+def foo()\n"
            return ""

        monkeypatch.setattr("ravencode.runtime.autogit._git", fake_git)
        result = await auto_commit()
        assert result == "[ok] committed 2 file(s): feat: def foo()"

    async def test_many_files_summary(self, monkeypatch) -> None:
        status = "\n".join(f" M f{i}.py" for i in range(8))
        async def fake_git(*args, cwd=None) -> str:
            if args[0] == "status":
                return status + "\n"
            if args[0] == "diff":
                return ""
            return ""

        monkeypatch.setattr("ravencode.runtime.autogit._git", fake_git)
        result = await auto_commit()
        assert result == "[ok] committed 8 file(s): fix: (no meaningful changes)"


class TestAutoCommitTool:
    async def test_delegates(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.runtime.autogit.auto_commit", AsyncMock(return_value="[ok] done"))
        assert await auto_commit_tool(message="m", path="p") == "[ok] done"

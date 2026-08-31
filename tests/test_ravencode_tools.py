from __future__ import annotations

import asyncio
import sys
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from ravencode.runtime import tools
from ravencode.runtime.question import Question, QuestionError
from ravencode.runtime.undo import UndoManager


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None, None, None]:
    ws_token = tools._workspace_var.set(None)
    depth_token = tools._task_depth.set(0)
    tools.set_permission_checker(None)
    yield
    tools._workspace_var.reset(ws_token)
    tools._task_depth.reset(depth_token)
    tools.set_permission_checker(None)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    return tmp_path


class _FakeProc:
    def __init__(self, out: bytes = b"", err: bytes = b"", rc: int = 0) -> None:
        self.out = out
        self.err = err
        self.returncode = rc
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.out, self.err

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


async def _wait_for_then_timeout(coro: object, timeout: object = None) -> None:
    if hasattr(coro, "__await__"):
        await coro
    raise TimeoutError


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_get_workspace_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    assert tools._get_workspace() == tmp_path.resolve()


def test_set_workspace_root_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", "other")
    tools.set_workspace_root(tmp_path)
    assert tools._get_workspace() == tmp_path.resolve()
    tools.set_workspace_root(str(tmp_path))
    assert tools._get_workspace() == tmp_path.resolve()


def test_confine_within(ws: Path) -> None:
    target = ws / "sub" / "f.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert tools._confine(str(target)) == target.resolve()


def test_confine_outside_raises(ws: Path) -> None:
    outside = ws.parent / "escape.txt"
    with pytest.raises(PermissionError):
        tools._confine(str(outside))


def test_compute_diff(ws: Path) -> None:
    diff = tools._compute_diff("a\nb\n", "a\nc\n", "f.txt")
    assert diff.startswith("--- f.txt")
    assert "+c" in diff


@pytest.mark.asyncio
async def test_safe_read_missing(ws: Path) -> None:
    content, err = await tools._safe_read(str(ws / "nope.txt"))
    assert content == ""
    assert "file not found" in err


@pytest.mark.asyncio
async def test_safe_read_truncated(ws: Path) -> None:
    target = ws / "big.txt"
    target.write_text("x" * 100, encoding="utf-8")
    content, err = await tools._safe_read(str(target), max_chars=10)
    assert err == ""
    assert content.startswith("x" * 10)
    assert "truncated" in content


@pytest.mark.asyncio
async def test_safe_read_error(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = ws / "f.txt"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(asyncio, "to_thread", AsyncMock(side_effect=OSError("boom")))
    content, err = await tools._safe_read(str(target))
    assert content == ""
    assert "cannot read" in err


@pytest.mark.asyncio
async def test_safe_write_new_file(ws: Path) -> None:
    mgr = UndoManager()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tools, "get_undo_manager", lambda: mgr)
    target = ws / "sub" / "new.txt"
    await tools._safe_write(str(target), "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    assert len(mgr._undo_stack) == 1
    assert mgr._undo_stack[0].original == ""
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_safe_write_existing(ws: Path) -> None:
    mgr = UndoManager()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(tools, "get_undo_manager", lambda: mgr)
    target = ws / "f.txt"
    target.write_text("old", encoding="utf-8")
    await tools._safe_write(str(target), "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert mgr._undo_stack[0].original == "old"
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# file tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_missing(ws: Path) -> None:
    out = await tools.read_file(str(ws / "nope.txt"))
    assert "file not found" in out


@pytest.mark.asyncio
async def test_write_file_ok(ws: Path) -> None:
    out = await tools.write_file(str(ws / "a.txt"), "content")
    assert out == "[ok] wrote 7 chars to " + str(ws / "a.txt")
    assert (ws / "a.txt").read_text(encoding="utf-8") == "content"


@pytest.mark.asyncio
async def test_write_file_permission_error(ws: Path) -> None:
    out = await tools.write_file(str(ws.parent / "evil.txt"), "x")
    assert out.startswith("[error]")


@pytest.mark.asyncio
async def test_edit_file_missing(ws: Path) -> None:
    out = await tools.edit_file(str(ws / "nope.txt"), "a", "b")
    assert "file not found" in out


@pytest.mark.asyncio
async def test_edit_file_old_not_found(ws: Path) -> None:
    target = ws / "f.txt"
    target.write_text("abc", encoding="utf-8")
    out = await tools.edit_file(str(target), "zzz", "b")
    assert "old_string not found" in out


@pytest.mark.asyncio
async def test_edit_file_multiple_occurrences(ws: Path) -> None:
    target = ws / "f.txt"
    target.write_text("aa", encoding="utf-8")
    out = await tools.edit_file(str(target), "a", "b")
    assert "provide more context" in out


@pytest.mark.asyncio
async def test_edit_file_preview(ws: Path) -> None:
    target = ws / "f.txt"
    target.write_text("old", encoding="utf-8")
    out = await tools.edit_file(str(target), "old", "new", preview=True)
    assert out.startswith("[diff for ")
    assert "+new" in out


@pytest.mark.asyncio
async def test_edit_file_applies(ws: Path) -> None:
    target = ws / "f.txt"
    target.write_text("old text", encoding="utf-8")
    out = await tools.edit_file(str(target), "old", "new")
    assert out == "[ok] applied edit to " + str(target)
    assert target.read_text(encoding="utf-8") == "new text"


@pytest.mark.asyncio
async def test_edit_file_write_permission_error(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = ws / "f.txt"
    target.write_text("abc", encoding="utf-8")
    monkeypatch.setattr(tools, "_safe_write", AsyncMock(side_effect=PermissionError("denied")))
    out = await tools.edit_file(str(target), "a", "b")
    assert out == "[error] denied"


@pytest.mark.asyncio
async def test_verify_file_missing(ws: Path) -> None:
    out = await tools.verify_file(str(ws / "nope.py"))
    assert "file not found" in out


@pytest.mark.asyncio
async def test_verify_file_python_syntax_error(ws: Path) -> None:
    (ws / "bad.py").write_text("def foo(:\n", encoding="utf-8")
    out = await tools.verify_file(str(ws / "bad.py"))
    assert "syntax error" in out
    assert "line 1" in out


@pytest.mark.asyncio
async def test_verify_file_json_ok(ws: Path) -> None:
    (ws / "data.json").write_text('{"a": 1}', encoding="utf-8")
    out = await tools.verify_file(str(ws / "data.json"))
    assert "[ok]" in out


@pytest.mark.asyncio
async def test_verify_file_json_invalid(ws: Path) -> None:
    (ws / "data.json").write_text("{oops", encoding="utf-8")
    out = await tools.verify_file(str(ws / "data.json"))
    assert "invalid JSON" in out


@pytest.mark.asyncio
async def test_verify_file_missing_tools_skips_gracefully(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("bin not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise)
    (ws / "good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    out = await tools.verify_file(str(ws / "good.py"))
    assert "[ok]" in out
    (ws / "data.json").write_text('{"a": 1}', encoding="utf-8")
    out = await tools.verify_file(str(ws / "data.json"))
    assert "[ok]" in out


@pytest.mark.asyncio
async def test_glob_files_basic(ws: Path) -> None:
    (ws / "a.py").write_text("x", encoding="utf-8")
    (ws / "b.txt").write_text("x", encoding="utf-8")
    (ws / "sub").mkdir()
    (ws / "sub" / "c.py").write_text("x", encoding="utf-8")
    results = await tools.glob_files("**/*.py")
    assert results == [str(Path("sub") / "c.py")]
    assert await tools.glob_files("*.py") == ["a.py", str(Path("sub") / "c.py")]


@pytest.mark.asyncio
async def test_glob_files_not_dir(ws: Path) -> None:
    results = await tools.glob_files("*.py", str(ws / "sub"))
    assert results == ["[error] directory not found: " + str(ws / "sub")]


@pytest.mark.asyncio
async def test_grep_files_basic(ws: Path) -> None:
    (ws / "a.py").write_text("line1\nneedle here\n", encoding="utf-8")
    results = await tools.grep_files("needle")
    assert len(results) == 1
    assert results[0]["file"] == "a.py"
    assert results[0]["line"] == 2


@pytest.mark.asyncio
async def test_grep_files_include_filter(ws: Path) -> None:
    (ws / "a.py").write_text("needle\n", encoding="utf-8")
    (ws / "b.txt").write_text("needle\n", encoding="utf-8")
    results = await tools.grep_files("needle", include="*.py")
    assert [r["file"] for r in results] == ["a.py"]


@pytest.mark.asyncio
async def test_grep_files_not_dir(ws: Path) -> None:
    results = await tools.grep_files("x", path=str(ws / "sub"))
    assert results == [{"error": "directory not found: " + str(ws / "sub")}]


@pytest.mark.asyncio
async def test_grep_files_result_cap(ws: Path) -> None:
    (ws / "a.txt").write_text("needle\n" * 250, encoding="utf-8")
    results = await tools.grep_files("needle")
    assert len(results) == 200


@pytest.mark.asyncio
async def test_grep_files_skips_directories(ws: Path) -> None:
    (ws / "sub").mkdir()
    (ws / "a.txt").write_text("needle\n", encoding="utf-8")
    results = await tools.grep_files("needle")
    assert [r["file"] for r in results] == ["a.txt"]


@pytest.mark.asyncio
async def test_grep_files_skips_unreadable(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (ws / "a.txt").write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(asyncio, "to_thread", AsyncMock(side_effect=PermissionError("denied")))
    results = await tools.grep_files("needle")
    assert results == []


@pytest.mark.asyncio
async def test_grep_files_regex(ws: Path) -> None:
    (ws / "a.py").write_text("foo\nbar123\nbaz\n", encoding="utf-8")
    results = await tools.grep_files(r"bar\d+", use_regex=True)
    assert len(results) == 1
    assert results[0]["line"] == 2
    assert results[0]["content"] == "bar123"


@pytest.mark.asyncio
async def test_grep_files_regex_no_match(ws: Path) -> None:
    (ws / "a.py").write_text("foo\nbar\n", encoding="utf-8")
    results = await tools.grep_files(r"\d+", use_regex=True)
    assert results == []


@pytest.mark.asyncio
async def test_grep_files_regex_invalid(ws: Path) -> None:
    results = await tools.grep_files("(", use_regex=True)
    assert results[0]["error"].startswith("invalid regex")


@pytest.mark.asyncio
async def test_grep_files_substring_still_works(ws: Path) -> None:
    (ws / "a.py").write_text("foo\n", encoding="utf-8")
    results = await tools.grep_files("fo", use_regex=False)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bash_empty() -> None:
    out = await tools.bash_exec("   ")
    assert out == "[error] empty command"


@pytest.mark.asyncio
async def test_bash_denied() -> None:
    out = await tools.bash_exec("malicious_cmd --flag")
    assert out == "[denied] command 'malicious_cmd' not in allowlist"


@pytest.mark.asyncio
async def test_bash_ok() -> None:
    out = await tools.bash_exec("python -c \"print('hello')\"")
    assert "hello" in out


@pytest.mark.asyncio
async def test_bash_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    monkeypatch.setattr(asyncio, "wait_for", _wait_for_then_timeout)
    out = await tools.bash_exec("echo x", timeout=1)
    assert out == "[timeout after 1s]"
    assert proc.killed


@pytest.mark.asyncio
async def test_bash_stderr_and_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(err=b"boom", rc=1)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    out = await tools.bash_exec("echo x")
    assert "[stderr]" in out
    assert "boom" in out
    assert "[exit code: 1]" in out


@pytest.mark.asyncio
async def test_bash_no_output(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    out = await tools.bash_exec("echo x")
    assert out == "(no output)"


# ---------------------------------------------------------------------------
# search tools
# ---------------------------------------------------------------------------


class _FakeDDGS:
    DEFAULT_RESULTS: tuple[dict[str, str], ...] = ({"title": "t", "href": "http://x", "body": "b"},)

    def __init__(self, results: list[dict[str, str]] | None = None) -> None:
        self._results = results if results is not None else list(_FakeDDGS.DEFAULT_RESULTS)

    def __enter__(self) -> _FakeDDGS:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def text(self, query: str, max_results: int) -> list[dict[str, str]]:
        return self._results


@pytest.mark.asyncio
async def test_ddg_search_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "duckduckgo_search", None)
    assert await tools._ddg_search("q", 5) is None


@pytest.mark.asyncio
async def test_ddg_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [{"title": "t", "href": "http://x", "body": "b"}]
    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(DDGS=_FakeDDGS))
    out = await tools._ddg_search("q", 5)
    assert out == results


@pytest.mark.asyncio
async def test_ddg_search_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomDDGS:
        def __enter__(self) -> _BoomDDGS:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def text(self, query: str, max_results: int) -> list[dict[str, str]]:
            raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(DDGS=_BoomDDGS))
    assert await tools._ddg_search("q", 5) is None


@pytest.mark.asyncio
async def test_ddg_search_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "duckduckgo_search", SimpleNamespace(DDGS=lambda: _FakeDDGS([])))
    assert await tools._ddg_search("q", 5) is None


class _Snip:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self, strip: bool = False) -> str:
        return self._text


class _Link:
    def __init__(self, title: str, href: str, snippet: str) -> None:
        self._title = title
        self._href = href
        self._snippet = _Snip(snippet)

    def get_text(self, strip: bool = False) -> str:
        return self._title

    def get(self, attr: str, default: str = "") -> str:
        return self._href if attr == "href" else default

    def find_next(self, tag: str, class_: str | None = None) -> _Snip:
        return self._snippet


@pytest.mark.asyncio
async def test_httpx_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = MagicMock()
    resp.text = "<html><body></body></html>"
    resp.raise_for_status = Mock()

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str] | None = None) -> MagicMock:
            return resp

    class _FakeSoup:
        def __init__(self, html: str, parser: str) -> None:
            pass

        def select(self, selector: str) -> list[_Link]:
            return [_Link("t", "http://x", "b")]

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=_FakeClient))
    monkeypatch.setitem(sys.modules, "bs4", SimpleNamespace(BeautifulSoup=_FakeSoup))
    out = await tools._httpx_search("q", 5)
    assert out == [{"title": "t", "href": "http://x", "body": "b"}]


@pytest.mark.asyncio
async def test_httpx_search_num_results_break(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = MagicMock()
    resp.text = "<html><body></body></html>"
    resp.raise_for_status = Mock()

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str] | None = None) -> MagicMock:
            return resp

    class _FakeSoup:
        def __init__(self, html: str, parser: str) -> None:
            pass

        def select(self, selector: str) -> list[_Link]:
            return [_Link("a", "http://a", "1"), _Link("b", "http://b", "2")]

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=_FakeClient))
    monkeypatch.setitem(sys.modules, "bs4", SimpleNamespace(BeautifulSoup=_FakeSoup))
    out = await tools._httpx_search("q", num_results=1)
    assert out == [{"title": "a", "href": "http://a", "body": "1"}]


@pytest.mark.asyncio
async def test_httpx_search_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "bs4", None)
    assert await tools._httpx_search("q", 5) is None


@pytest.mark.asyncio
async def test_httpx_search_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FailClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str] | None = None) -> None:
            raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=_FailClient))
    monkeypatch.setitem(sys.modules, "bs4", SimpleNamespace(BeautifulSoup=lambda h, p: None))
    assert await tools._httpx_search("q", 5) is None


def test_urlencode() -> None:
    assert tools._urlencode("a b&c") == "a%20b%26c"


@pytest.mark.asyncio
async def test_web_search_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "_ddg_search", AsyncMock(return_value=None))
    monkeypatch.setattr(tools, "_httpx_search", AsyncMock(return_value=None))
    assert await tools.web_search("q") == "(no results)"


@pytest.mark.asyncio
async def test_web_search_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tools,
        "_ddg_search",
        AsyncMock(return_value=[{"title": "t", "body": "b", "href": "http://x"}]),
    )
    out = await tools.web_search("q")
    assert "\u2022 t" in out
    assert "b" in out
    assert "http://x" in out


# ---------------------------------------------------------------------------
# web_fetch / think / task_delegate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_fetch_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "validate_url", Mock(return_value=False))
    out = await tools.web_fetch("http://127.0.0.1/")
    assert out.startswith("[denied]")


@pytest.mark.asyncio
async def test_web_fetch_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = MagicMock()
    resp.text = "<html>ok</html>"
    resp.raise_for_status = Mock()
    monkeypatch.setattr(tools, "validate_url", Mock(return_value=True))
    monkeypatch.setattr(tools, "safe_fetch_async", AsyncMock(return_value=resp))
    out = await tools.web_fetch("https://example.com/")
    assert out == "<html>ok</html>"


@pytest.mark.asyncio
async def test_web_fetch_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "validate_url", Mock(return_value=True))
    monkeypatch.setattr(tools, "safe_fetch_async", AsyncMock(side_effect=ValueError("blocked")))
    out = await tools.web_fetch("https://example.com/")
    assert "[denied]" in out


@pytest.mark.asyncio
async def test_web_fetch_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "validate_url", Mock(return_value=True))
    monkeypatch.setattr(tools, "safe_fetch_async", AsyncMock(side_effect=RuntimeError("boom")))
    out = await tools.web_fetch("https://example.com/")
    assert out.startswith("[error]")


@pytest.mark.asyncio
async def test_think() -> None:
    assert await tools.think("step 1") == "[thinking: step 1]"


@pytest.mark.asyncio
async def test_task_delegate_max_depth() -> None:
    token = tools._task_depth.set(tools._MAX_TASK_DEPTH)
    try:
        out = await tools.task_delegate("task")
        assert "max task delegation depth" in out
    finally:
        tools._task_depth.reset(token)


class _FakeReAct:
    def __init__(self, config: object = None, conversation: object = None) -> None:
        self.seen_prompt: str = ""
        self.config = config

    async def run(self, prompt: str) -> str:
        self.seen_prompt = prompt
        return "done"


@pytest.mark.asyncio
async def test_task_delegate_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.core.prompts.get_prompt", Mock(return_value="SUB"))
    fake = _FakeReAct()
    monkeypatch.setattr("ravencode.runtime.agent_core.ReActAgent", lambda **kw: fake)
    out = await tools.task_delegate("build it", context="parent context")
    assert out == "done"
    assert "Task: build it" in fake.seen_prompt
    assert "parent context" in fake.seen_prompt


@pytest.mark.asyncio
async def test_task_delegate_with_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.core.prompts.get_prompt", Mock(return_value="SUB"))
    fake = _FakeReAct()
    monkeypatch.setattr("ravencode.runtime.agent_core.ReActAgent", lambda **kw: fake)
    tools.set_agent_memory({"note": "remember me"})
    try:
        await tools.task_delegate("task")
    finally:
        tools.set_agent_memory(None)
    assert "remember me" in fake.seen_prompt


@pytest.mark.asyncio
async def test_task_delegate_propagates_memory_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from ravencode.runtime.agent_core import AgentConfig

    monkeypatch.setattr("ravencode.core.prompts.get_prompt", Mock(return_value="SUB"))
    captured: dict[str, object] = {}

    def _factory(**kw: object) -> object:
        captured.update(kw)
        return _FakeReAct(**kw)

    monkeypatch.setattr("ravencode.runtime.agent_core.ReActAgent", _factory)
    tools.set_agent_memory({"config": {"memory_path": "/tmp/mem.json"}})
    try:
        await tools.task_delegate("task")
    finally:
        tools.set_agent_memory(None)
    cfg = captured.get("config")
    assert cfg is not None
    assert isinstance(cfg, AgentConfig)
    assert cfg.memory_path == "/tmp/mem.json"


@pytest.mark.asyncio
async def test_task_delegate_no_parent_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from ravencode.runtime.agent_core import AgentConfig

    monkeypatch.setattr("ravencode.core.prompts.get_prompt", Mock(return_value="SUB"))
    captured: dict[str, object] = {}

    def _factory(**kw: object) -> object:
        captured.update(kw)
        return _FakeReAct(**kw)

    monkeypatch.setattr("ravencode.runtime.agent_core.ReActAgent", _factory)
    tools.set_agent_memory(None)
    await tools.task_delegate("task")
    cfg = captured.get("config")
    assert cfg is not None
    assert isinstance(cfg, AgentConfig)
    assert cfg.memory_path is None


@pytest.mark.asyncio
async def test_delegate_role_prompt_verify_routes_to_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    from ravencode.core import prompts as prompt_mod

    seen: list[str] = []

    def fake_get(prompt_type: str, **kwargs: str) -> str:
        seen.append(prompt_type)
        return prompt_type

    monkeypatch.setattr(prompt_mod, "get_prompt", fake_get)
    tools._delegate_role_prompt("verify that the result is correct")
    assert seen[-1] == "verifier"


@pytest.mark.asyncio
async def test_delegate_role_prompt_verify_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    from ravencode.core import prompts as prompt_mod

    seen: list[str] = []

    def fake_get(prompt_type: str, **kwargs: str) -> str:
        seen.append(prompt_type)
        return prompt_type

    monkeypatch.setattr(prompt_mod, "get_prompt", fake_get)
    for kw in ("debug it", "plan the steps", "write a function", "review the diff", "unknown task"):
        tools._delegate_role_prompt(kw)
    assert seen == ["debugger", "planner", "coder", "verifier", "delegate"]


def test_verifier_prompt_registered() -> None:
    from ravencode.core.prompts import VERIFIER, get_prompt

    assert get_prompt(VERIFIER)  # does not raise and is non-empty
    assert "[ok]" in get_prompt(VERIFIER)


# ---------------------------------------------------------------------------
# git tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_git_cmd_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(out=b"clean")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    out = await tools._git_cmd("status", cwd=".")
    assert out == "clean"


@pytest.mark.asyncio
async def test_git_cmd_stderr_and_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(out=b"", err=b"err", rc=1)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    out = await tools._git_cmd("status")
    assert "err" in out
    assert "[exit code: 1]" in out


@pytest.mark.asyncio
async def test_git_cmd_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    monkeypatch.setattr(asyncio, "wait_for", _wait_for_then_timeout)
    out = await tools._git_cmd("status")
    assert out == "[timeout]"
    assert proc.killed


@pytest.mark.asyncio
async def test_git_cmd_timeout_kill_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _KillFailsProc(_FakeProc):
        async def wait(self) -> int:
            raise ProcessLookupError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=_KillFailsProc()))
    monkeypatch.setattr(asyncio, "wait_for", _wait_for_then_timeout)
    out = await tools._git_cmd("status")
    assert out == "[timeout]"


@pytest.mark.asyncio
async def test_git_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _FakeProc(out=b"ok")
    captured: list[list[str]] = []
    original = asyncio.create_subprocess_exec

    async def fake_exec(*args: object, **kwargs: object) -> _FakeProc:
        captured.append([str(a) for a in args])
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await tools.git_status() == "ok"
    assert await tools.git_diff() == "ok"
    assert await tools.git_diff(staged=True) == "ok"
    assert await tools.git_log(max_count=3) == "ok"
    assert await tools.git_commit("msg") == "ok"
    assert await tools.git_add("a.py b.py") == "ok"
    assert any("--cached" in c for c in captured)
    assert any("--max-count=3" in c for c in captured)
    assert any("add" in c and "a.py" in c and "b.py" in c for c in captured)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", original)


# ---------------------------------------------------------------------------
# read_image / create_artifact error / undo-redo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_image_outside_workspace(ws: Path) -> None:
    out = await tools.read_image(str(ws.parent / "x.png"))
    assert out.startswith("[error]")


@pytest.mark.asyncio
async def test_read_image_missing(ws: Path) -> None:
    out = await tools.read_image(str(ws / "nope.png"))
    assert out == "[error] file not found: " + str(ws / "nope.png")


@pytest.mark.asyncio
async def test_read_image_bad_format(ws: Path) -> None:
    target = ws / "f.txt"
    target.write_text("x", encoding="utf-8")
    out = await tools.read_image(str(target))
    assert "unsupported image format" in out


@pytest.mark.asyncio
async def test_read_image_ok(ws: Path) -> None:
    target = ws / "pic.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    out = await tools.read_image(str(target))
    assert out.startswith("Image (")
    assert "data:image/png;base64," in out


@pytest.mark.asyncio
async def test_create_artifact_generic_error(ws: Path) -> None:
    out = await tools.create_artifact("t", "html", {"not": "a string"})  # type: ignore[arg-type]
    assert "error" in out


@pytest.mark.asyncio
async def test_undo_empty(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = UndoManager()
    monkeypatch.setattr(tools, "get_undo_manager", lambda: mgr)
    assert await tools.undo_action() == "[undo] nothing to undo"
    assert await tools.redo_action() == "[redo] nothing to redo"


@pytest.mark.asyncio
async def test_undo_redo_cycle(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = UndoManager()
    monkeypatch.setattr(tools, "get_undo_manager", lambda: mgr)
    target = ws / "f.txt"
    await tools.write_file(str(target), "v2")
    assert await tools.undo_action() == "[undo] write on " + str(target.resolve())
    assert target.read_text(encoding="utf-8") == ""
    assert await tools.redo_action() == "[redo] write on " + str(target.resolve())
    assert target.read_text(encoding="utf-8") == "v2"


# ---------------------------------------------------------------------------
# checkpoint / lsp / sandbox / diff / format / autogit / skills / todo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkpoint_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = MagicMock()
    mgr.save = AsyncMock(return_value="cp_1")
    mgr.restore = AsyncMock(return_value="restored")
    mgr.list = Mock(return_value=[{"id": "cp_1", "description": "d", "created": 123}])
    monkeypatch.setattr("ravencode.runtime.checkpoints.get_checkpoint_manager", Mock(return_value=mgr))
    assert await tools.checkpoint_save_tool("desc") == "cp_1"
    assert await tools.checkpoint_restore_tool("cp_1") == "restored"
    assert await tools.checkpoint_list_tool() == "cp_1: d (123)"
    mgr.list = Mock(return_value=[])
    assert await tools.checkpoint_list_tool() == "(no checkpoints)"


@pytest.mark.asyncio
async def test_lsp_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.runtime.lsp.lsp_completion", AsyncMock(return_value="comp"))
    monkeypatch.setattr("ravencode.runtime.lsp.lsp_definition", AsyncMock(return_value="def"))
    monkeypatch.setattr("ravencode.runtime.lsp.lsp_references", AsyncMock(return_value="refs"))
    monkeypatch.setattr("ravencode.runtime.lsp.lsp_hover", AsyncMock(return_value="hover"))
    assert await tools.lsp_completion_tool("a.py", 0, 0) == "comp"
    assert await tools.lsp_definition_tool("a.py", 0, 0) == "def"
    assert await tools.lsp_references_tool("a.py", 0, 0) == "refs"
    assert await tools.lsp_hover_tool("a.py", 0, 0) == "hover"


@pytest.mark.asyncio
async def test_sandbox_exec_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = MagicMock()
    sandbox.run_code = AsyncMock(return_value="out")
    monkeypatch.setattr("ravencode.runtime.sandbox.get_sandbox", Mock(return_value=sandbox))
    assert await tools.sandbox_exec_tool("code") == "out"


@pytest.mark.asyncio
async def test_smart_edit_and_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.runtime.diff.smart_edit", Mock(return_value="edited"))
    monkeypatch.setattr("ravencode.runtime.diff.apply_patch", Mock(return_value="patched"))
    assert await tools.smart_edit_tool("a.py", old_text="x", new_text="y") == "edited"
    assert await tools.patch_file_tool("a.py", "diff") == "patched"


@pytest.mark.asyncio
async def test_format_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.runtime.formatters.format_file", AsyncMock(return_value="formatted"))
    monkeypatch.setattr("ravencode.runtime.formatters.format_files", AsyncMock(return_value="formatted many"))
    assert await tools.format_file_tool("a.py") == "formatted"
    assert await tools.format_files_tool(["a.py", "b.py"]) == "formatted many"


@pytest.mark.asyncio
async def test_auto_commit_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.runtime.autogit.auto_commit", AsyncMock(return_value="committed"))
    assert await tools.auto_commit_tool("msg") == "committed"


@pytest.mark.asyncio
async def test_skill_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.runtime.skills.load_skill", Mock(return_value="loaded"))
    monkeypatch.setattr("ravencode.runtime.skills.download_skill", AsyncMock(return_value="downloaded"))
    monkeypatch.setattr("ravencode.runtime.skills.set_skill_registry", Mock(return_value="registry"))
    assert await tools.load_skill("x") == "loaded"
    assert await tools.download_skill("x") == "downloaded"
    assert await tools.set_skill_registry("https://r.example.com") == "registry"


@pytest.mark.asyncio
async def test_todo_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.runtime.todo.todo_write", Mock(return_value="wrote"))
    monkeypatch.setattr("ravencode.runtime.todo.todo_list", Mock(return_value="list"))
    monkeypatch.setattr("ravencode.runtime.todo.todo_update", Mock(return_value="updated"))
    monkeypatch.setattr("ravencode.runtime.todo.todo_clear", Mock())
    assert await tools.todo_write([{"content": "x"}]) == "wrote"
    assert await tools.todo_list("pending") == "list"
    assert await tools.todo_update("1", "completed") == "updated"
    assert await tools.todo_clear() == "(todo list cleared)"


# ---------------------------------------------------------------------------
# question / anchored / browser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_question_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Question] = []

    async def _capture(q: Question) -> str:
        captured.append(q)
        return "answer"

    monkeypatch.setattr("ravencode.runtime.question.ask_question", AsyncMock(side_effect=_capture))
    out = await tools.question_tool("pick", header="H", options=[{"label": "a", "description": "b"}], multiple=True)
    assert out == "answer"
    q = captured[0]
    assert q.question == "pick"
    assert q.header == "H"
    assert q.options == [{"label": "a", "description": "b"}]
    assert q.multiple is True


@pytest.mark.asyncio
async def test_question_tool_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Question] = []

    async def _capture(q: Question) -> str:
        captured.append(q)
        return "answer"

    monkeypatch.setattr("ravencode.runtime.question.ask_question", AsyncMock(side_effect=_capture))
    await tools.question_tool("pick")
    q = captured[0]
    assert q.options == []
    assert q.multiple is False


@pytest.mark.asyncio
async def test_anchored_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ravencode.runtime.anchored.anchored_summary", Mock(return_value=""))
    monkeypatch.setattr("ravencode.runtime.anchored.update_anchored_summary", Mock(return_value="w"))
    monkeypatch.setattr("ravencode.runtime.anchored.append_anchored_summary", Mock(return_value="a"))
    monkeypatch.setattr("ravencode.runtime.anchored.clear_anchored_summary", Mock(return_value="c"))
    assert await tools.anchored_summary_read() == "(no anchored summary)"
    assert await tools.anchored_summary_write("t") == "w"
    assert await tools.anchored_summary_append("t") == "a"
    assert await tools.anchored_summary_clear() == "c"
    monkeypatch.setattr("ravencode.runtime.anchored.anchored_summary", Mock(return_value="val"))
    assert await tools.anchored_summary_read() == "val"


@pytest.mark.asyncio
async def test_browser_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    for fn in ("navigate", "click", "type", "screenshot", "get_html", "evaluate", "close"):
        monkeypatch.setattr(f"ravencode.runtime.browser.browser_{fn}", AsyncMock(return_value="ok"))
    assert await tools.browser_navigate("http://x") == "ok"
    assert await tools.browser_click("#btn") == "ok"
    assert await tools.browser_type("#in", "text") == "ok"
    assert await tools.browser_screenshot() == "ok"
    assert await tools.browser_get_html() == "ok"
    assert await tools.browser_evaluate("1+1") == "ok"
    assert await tools.browser_close() == "ok"


# ---------------------------------------------------------------------------
# canvas / nodes / cron / sandbox policy / talk
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canvas_render_handler() -> None:
    components: list[dict[str, object]] = [
        {"type": "text", "content": "plain"},
        {"type": "code", "language": "py", "content": "print(1)"},
        {"type": "table", "headers": ["a", "b"], "rows": [[1, 2], [3, 4]]},
        {"type": "mermaid", "content": "graph TD"},
        {"type": "alert", "level": "warning", "content": "careful"},
        {"type": "list", "items": ["x", "y"]},
        {"type": "unknown", "content": "fallback"},
    ]
    out = await tools._canvas_render_handler(components)
    assert "plain" in out
    assert "```py" in out
    assert "a | b" in out
    assert "```mermaid" in out
    assert "> [!WARNING]" in out
    assert "- x" in out
    assert "fallback" in out


@pytest.mark.asyncio
async def test_nodes_list_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.tools.nodes.nodes_list", AsyncMock(return_value="nodes"))
    assert await tools._nodes_list_handler() == "nodes"


@pytest.mark.asyncio
async def test_nodes_list_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "raven.tools.nodes", None)
    assert await tools._nodes_list_handler() == "(nodes module not available)"


@pytest.mark.asyncio
async def test_cron_handlers_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.plugins.cron.plugin.schedule", AsyncMock(return_value="scheduled"))
    monkeypatch.setattr("raven.plugins.cron.plugin.list_schedules", AsyncMock(return_value="schedules"))
    monkeypatch.setattr("raven.plugins.cron.plugin.cancel_schedule", AsyncMock(return_value="cancelled"))
    assert await tools._cron_schedule_handler("0 9 * * *", "task", "t1") == "scheduled"
    assert await tools._cron_list_handler() == "schedules"
    assert await tools._cron_cancel_handler("t1") == "cancelled"


@pytest.mark.asyncio
async def test_cron_handlers_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "raven.plugins.cron.plugin", None)
    assert await tools._cron_schedule_handler("0 9 * * *", "task") == "[error] cron plugin not available"
    assert await tools._cron_list_handler() == "(cron plugin not available)"
    assert await tools._cron_cancel_handler("t1") == "[error] cron plugin not available"


@pytest.mark.asyncio
async def test_sandbox_policy_get_set() -> None:
    tools._current_sandbox_policy = "main"
    assert await tools._sandbox_policy_handler() == "Current sandbox policy: main"
    assert await tools._sandbox_policy_handler("code-exec") == "Sandbox policy set to: code-exec"
    assert tools._current_sandbox_policy == "code-exec"
    out = await tools._sandbox_policy_handler("bogus")
    assert out.startswith("[error] unknown policy: bogus")


class _FakeTTSProvider:
    SYSTEM: _FakeTTSProvider

    def __init__(self, value: str) -> None:
        if value not in ("system", "gtts", "edge", "elevenlabs"):
            raise ValueError(value)
        self.value = value


_FakeTTSProvider.SYSTEM = _FakeTTSProvider("system")


class _FakeTTSConfig:
    def __init__(self, provider: object = "system", voice: str = "") -> None:
        self.provider = provider
        self.voice = voice


class _FakeTTS:
    def __init__(self, config: object) -> None:
        self.config = config

    def synthesize(self, text: str, output_path: str = "") -> str:
        return "C:/fake/audio.mp3"


@pytest.mark.asyncio
async def test_talk_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.voice.tts.TTSProvider", _FakeTTSProvider)
    monkeypatch.setattr("raven.voice.tts.TTSConfig", _FakeTTSConfig)
    monkeypatch.setattr("raven.voice.tts.TextToSpeech", _FakeTTS)
    out = await tools._talk_handler("hello")
    assert out == "Audio saved to C:/fake/audio.mp3"


@pytest.mark.asyncio
async def test_talk_handler_invalid_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.voice.tts.TTSProvider", _FakeTTSProvider)
    monkeypatch.setattr("raven.voice.tts.TTSConfig", _FakeTTSConfig)
    monkeypatch.setattr("raven.voice.tts.TextToSpeech", _FakeTTS)
    out = await tools._talk_handler("hello", provider="bogus")
    assert "Audio saved to" in out


# ---------------------------------------------------------------------------
# registry / execute_tool
# ---------------------------------------------------------------------------


def test_is_dangerous() -> None:
    assert tools.is_dangerous("write") is True
    assert tools.is_dangerous("read") is False
    assert tools.is_dangerous("__missing__") is False


def test_get_tool_definitions_plan_mode() -> None:
    names = {d["function"]["name"] for d in tools.get_tool_definitions(plan_mode=False)}
    assert "read" in names
    assert "write" in names
    plan_names = {d["function"]["name"] for d in tools.get_tool_definitions(plan_mode=True)}
    assert "read" in plan_names
    assert "write" not in plan_names


def test_ensure_plugin_tools_registers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "_plugin_tools_loaded", False)
    reg = MagicMock()
    reg.all_tools = Mock(return_value={"extra_tool": {"name": "extra_tool", "parameters": {}}})
    monkeypatch.setattr("ravencode.runtime.plugins.get_plugin_registry", Mock(return_value=reg))
    tools.get_tool_definitions()
    assert "extra_tool" in tools.MODULE_TOOLS
    assert tools._plugin_tools_loaded is True
    tools.MODULE_TOOLS.pop("extra_tool", None)


def test_ensure_plugin_tools_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "_plugin_tools_loaded", False)
    monkeypatch.setitem(sys.modules, "ravencode.runtime.plugins", None)
    assert isinstance(tools.get_tool_definitions(), list)
    assert tools._plugin_tools_loaded is False


@pytest.mark.asyncio
async def test_execute_tool_unknown() -> None:
    out = await tools.execute_tool("__nope__", {})
    assert out == "[error] unknown tool: __nope__"


@pytest.mark.asyncio
async def test_execute_tool_validation_error() -> None:
    out = await tools.execute_tool("think", {})
    assert out.startswith("[validation_error]")


@pytest.mark.asyncio
async def test_execute_tool_denied() -> None:
    tools.set_permission_checker(lambda name, args: (False, "not allowed"))
    out = await tools.execute_tool("think", {"reasoning": "x"})
    assert out == "[denied] not allowed"


@pytest.mark.asyncio
async def test_execute_tool_list_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _handler(**kwargs: object) -> list[str]:
        return ["a", "b"]

    monkeypatch.setitem(
        tools.MODULE_TOOLS,
        "__fake_list",
        {"name": "__fake_list", "parameters": {"type": "object", "properties": {}}, "handler": _handler},
    )
    out = await tools.execute_tool("__fake_list", {})
    assert out == "a\nb"


@pytest.mark.asyncio
async def test_execute_tool_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _handler(**kwargs: object) -> str:
        return "x" * 20_000

    monkeypatch.setitem(
        tools.MODULE_TOOLS,
        "__fake_long",
        {"name": "__fake_long", "parameters": {"type": "object", "properties": {}}, "handler": _handler},
    )
    out = await tools.execute_tool("__fake_long", {})
    assert len(out) == 15_000 + len("\n\n[... output truncated to 15k chars ...]")
    assert "truncated" in out


@pytest.mark.asyncio
async def test_execute_tool_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _handler(**kwargs: object) -> str:
        raise RuntimeError("boom")

    monkeypatch.setitem(
        tools.MODULE_TOOLS,
        "__fake_err",
        {"name": "__fake_err", "parameters": {"type": "object", "properties": {}}, "handler": _handler},
    )
    out = await tools.execute_tool("__fake_err", {})
    assert out == "[execution_error] __fake_err failed: boom"


@pytest.mark.asyncio
async def test_execute_tool_question_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ravencode.runtime.question.ask_question",
        AsyncMock(side_effect=QuestionError({"question": "x"})),
    )
    with pytest.raises(QuestionError):
        await tools.execute_tool("question", {"question": "x"})


def test_get_permission_for_tool_default() -> None:
    assert tools._get_permission_for_tool("read", {}) == (True, "")


def test_get_permission_for_tool_tuple_result() -> None:
    tools.set_permission_checker(lambda name, args: (0, "nope"))
    assert tools._get_permission_for_tool("read", {}) == (False, "nope")

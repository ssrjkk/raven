from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.coder.models import (
    CodeFile,
    CodeSymbol,
    CodingSession,
    ReviewComment,
    ReviewSeverity,
    SessionStatus,
)
from raven.core.gateway.commands.code import CodeCommand


class _FakeGateway:
    def __init__(self) -> None:
        self._send = AsyncMock()
        self._check_permission = MagicMock(return_value=True)
        self.db = SimpleNamespace(db_path=":memory:")


def _ctx(args: list[str] | None = None) -> Any:
    return SimpleNamespace(
        args=args or [],
        user={"id": "u1"},
        event=SimpleNamespace(channel="web", session_id="sid-1", user_id="u1"),
    )


def _sent(gw: _FakeGateway) -> tuple[str, str, str]:
    call = gw._send.await_args_list[-1]
    return call.args[0], call.args[1], call.args[2]


class _FakeIndexer:
    def __init__(self, root: str) -> None:
        self.root = root
        self.index_calls: list[int] = []
        self.search_results: list[CodeFile] = []
        self.summary_data: dict[str, Any] = {"files": 3, "languages": {"python": 3}}

    def index(self, max_files: int = 5000) -> dict[str, CodeFile]:
        self.index_calls.append(max_files)
        return {}

    def search(self, query: str, max_results: int = 20) -> list[CodeFile]:
        return self.search_results

    def summary(self) -> dict[str, Any]:
        return self.summary_data


class _FakeReviewer:
    def __init__(self) -> None:
        self.comments: list[ReviewComment] = []

    async def review_file(self, file_path: str, content: str, language: str = "") -> list[ReviewComment]:
        return self.comments


class _FakeMgr:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = db_path
        self.created: list[CodingSession] = []
        self.updated: list[CodingSession] = []
        self.fetched: CodingSession | None = None

    async def create_session(self, session: CodingSession) -> CodingSession:
        self.created.append(session)
        return session

    async def get_session(self, session_id: str) -> CodingSession | None:
        return self.fetched

    async def update_session(self, session: CodingSession) -> None:
        self.updated.append(session)


@pytest.fixture(autouse=True)
def _no_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.commands.code.get_policy_for_channel", lambda ch: None)


@pytest.fixture(autouse=True)
def _no_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.commands.code.settings", SimpleNamespace(resolved_workspace=None)
    )


def test_code_name_and_description() -> None:
    cmd = CodeCommand(_FakeGateway())
    assert cmd.name == "code"
    assert cmd.description == "Code management"


async def test_code_policy_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.commands.code.check_tool_allowed",
        lambda policy, action, ch: (False, "read-only channel"),
    )
    monkeypatch.setattr(
        "raven.core.gateway.commands.code.get_policy_for_channel", lambda ch: object()
    )
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Access denied: read-only channel"


async def test_code_permission_denied() -> None:
    gw = _FakeGateway()
    gw._check_permission = MagicMock(return_value=False)
    assert await CodeCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Access denied: insufficient permissions"


async def test_code_help_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx()) is True
    assert "Code commands:" in _sent(gw)[2]


async def test_code_index_no_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    holder: dict[str, _FakeIndexer] = {}

    def _factory(root: str) -> _FakeIndexer:
        inst = _FakeIndexer(root)
        holder["last"] = inst
        return inst

    monkeypatch.setattr("raven.core.coder.indexer.CodeIndexer", _factory)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["index", "/some/path"])) is True
    msgs = [c.args[2] for c in gw._send.await_args_list]
    assert msgs[0] == "Indexing /some/path..."
    assert "Indexed 3 files" in msgs[1]
    assert "python:3" in msgs[1]
    assert holder["last"].index_calls == [2000]


async def test_code_index_with_workspace_confines(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = Path("/workspace")
    monkeypatch.setattr(
        "raven.core.gateway.commands.code.settings", SimpleNamespace(resolved_workspace=ws)
    )
    monkeypatch.setattr(
        "raven.core.gateway.commands.code.confine_path",
        lambda path, base: "/workspace/confined",
    )
    monkeypatch.setattr("raven.core.coder.indexer.CodeIndexer", _FakeIndexer)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["index", "src"])) is True
    assert gw._send.await_args_list[0].args[2] == "Indexing /workspace/confined..."


async def test_code_index_workspace_escape_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = Path("/workspace")
    monkeypatch.setattr(
        "raven.core.gateway.commands.code.settings", SimpleNamespace(resolved_workspace=ws)
    )

    def _boom(path: str, base: Path) -> Path:
        raise PermissionError("outside workspace")

    monkeypatch.setattr("raven.core.gateway.commands.code.confine_path", _boom)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["index", "../etc"])) is True
    assert _sent(gw)[2] == "Access denied: outside workspace"


async def test_code_search_no_args_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["search"])) is True
    # "search" with no sub_args is not matched -> falls to help branch
    assert "Code commands:" in _sent(gw)[2]


async def test_code_search_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    holder: dict[str, _FakeIndexer] = {}

    def _factory(root: str) -> _FakeIndexer:
        inst = _FakeIndexer(root)
        holder["last"] = inst
        return inst

    monkeypatch.setattr("raven.core.coder.indexer.CodeIndexer", _factory)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["search", "foo"])) is True
    assert _sent(gw)[2] == "No results for 'foo'"


async def test_code_search_with_results(monkeypatch: pytest.MonkeyPatch) -> None:
    holder: dict[str, _FakeIndexer] = {}

    def _factory(root: str) -> _FakeIndexer:
        inst = _FakeIndexer(root)
        inst.search_results = [
            CodeFile(path="a.py", language="python", symbols=[CodeSymbol(name="Alpha"), CodeSymbol(name="Beta")])
        ]
        holder["last"] = inst
        return inst

    monkeypatch.setattr("raven.core.coder.indexer.CodeIndexer", _factory)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["search", "alpha beta"])) is True
    out = _sent(gw)[2]
    assert "Results for 'alpha beta'" in out
    assert "a.py [python] Alpha, Beta" in out


async def test_code_review_file_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["review", "/no/such/file.py"])) is True
    assert _sent(gw)[2].startswith("File not found:")


async def test_code_review_confine_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = Path("/workspace")
    monkeypatch.setattr(
        "raven.core.gateway.commands.code.settings", SimpleNamespace(resolved_workspace=ws)
    )

    def _boom(path: str, base: Path) -> Path:
        raise PermissionError("escape")

    monkeypatch.setattr("raven.core.gateway.commands.code.confine_path", _boom)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["review", "../etc/passwd"])) is True
    assert _sent(gw)[2] == "Access denied: escape"


async def test_code_review_no_issues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "clean.py"
    f.write_text("x = 1\n", encoding="utf-8")
    rv = _FakeReviewer()
    rv.comments = []
    monkeypatch.setattr("raven.core.coder.review.CodeReviewer", lambda: rv)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["review", str(f)])) is True
    assert _sent(gw)[2] == "✅ No issues found!"


async def test_code_review_with_issues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "dirty.py"
    f.write_text("x = 1\n", encoding="utf-8")
    rv = _FakeReviewer()
    rv.comments = [
        ReviewComment(line=3, severity=ReviewSeverity.CRITICAL, message="bad"),
        ReviewComment(line=7, severity=ReviewSeverity.WARNING, message="meh"),
    ]
    monkeypatch.setattr("raven.core.coder.review.CodeReviewer", lambda: rv)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["review", str(f)])) is True
    out = _sent(gw)[2]
    assert f"Review: {f.name}" in out
    assert "🔴 L3: bad" in out
    assert "🟡 L7: meh" in out


async def test_code_review_many_comments_truncates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "many.py"
    f.write_text("x = 1\n", encoding="utf-8")
    rv = _FakeReviewer()
    rv.comments = [
        ReviewComment(line=i, severity=ReviewSeverity.SUGGESTION, message=f"s{i}") for i in range(20)
    ]
    monkeypatch.setattr("raven.core.coder.review.CodeReviewer", lambda: rv)
    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _FakeMgr)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["review", str(f)])) is True
    assert "... and 5 more" in _sent(gw)[2]


async def test_code_start(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[_FakeMgr] = []

    def _factory(db_path: str | Path) -> _FakeMgr:
        m = _FakeMgr(db_path)
        captured.append(m)
        return m

    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _factory)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["start", "build a thing"])) is True
    assert len(captured[0].created) == 1
    sess = captured[0].created[0]
    assert sess.goal == "build a thing"
    out = _sent(gw)[2]
    assert "Coding session started:" in out
    assert "Goal: build a thing" in out


async def test_code_status_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _factory(db_path: str | Path) -> _FakeMgr:
        m = _FakeMgr(db_path)
        m.fetched = None
        return m

    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _factory)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["status", "abc12345"])) is True
    assert _sent(gw)[2] == "Session not found: abc12345"


async def test_code_status_found(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = CodingSession(
        goal="ship it", status=SessionStatus.ACTIVE, files=["a.py", "b.py"], history=[{"role": "user"}]
    )

    def _factory(db_path: str | Path) -> _FakeMgr:
        m = _FakeMgr(db_path)
        m.fetched = sess
        return m

    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _factory)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["status", sess.id])) is True
    out = _sent(gw)[2]
    assert f"Session: {sess.id[:8]}" in out
    assert "Goal: ship it" in out
    assert "Files: 2" in out
    assert "Messages: 1" in out


async def test_code_end_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    def _factory(db_path: str | Path) -> _FakeMgr:
        m = _FakeMgr(db_path)
        m.fetched = None
        return m

    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _factory)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["end", "deadbeef"])) is True
    assert _sent(gw)[2] == "Session not found: deadbeef"


async def test_code_end_marks_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    sess = CodingSession(goal="x", status=SessionStatus.ACTIVE)
    captured: list[_FakeMgr] = []

    def _factory(db_path: str | Path) -> _FakeMgr:
        m = _FakeMgr(db_path)
        m.fetched = sess
        captured.append(m)
        return m

    monkeypatch.setattr("raven.core.coder.session.CodingSessionManager", _factory)
    gw = _FakeGateway()
    assert await CodeCommand(gw).execute(_ctx(args=["end", sess.id])) is True
    assert captured[0].updated == [sess]
    assert sess.status is SessionStatus.COMPLETED
    assert _sent(gw)[2] == f"Session {sess.id[:8]} ended."

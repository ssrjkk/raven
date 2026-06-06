from __future__ import annotations


import pytest

from raven.core.coder.indexer import CodeIndexer
from raven.core.coder.models import (
    CodeFile,
    CodeSymbol,
    CodingSession,
    ReviewComment,
    ReviewSeverity,
    SessionStatus,
    SymbolKind,
)
from raven.core.coder.review import CodeReviewer
from raven.core.coder.session import CodingSessionManager


class TestCodeFile:
    def test_create_code_file(self):
        f = CodeFile(path="/test/file.py", language="python", size=100, lines=5)
        assert f.path == "/test/file.py"
        assert f.language == "python"
        assert f.size == 100
        assert f.lines == 5

    def test_code_file_defaults(self):
        f = CodeFile(path="/test/file.py")
        assert f.language == ""
        assert f.symbols == []


class TestCodeSymbol:
    def test_create_symbol(self):
        s = CodeSymbol(name="my_func", kind=SymbolKind.FUNCTION, line=10)
        assert s.name == "my_func"
        assert s.kind == SymbolKind.FUNCTION
        assert s.line == 10

    def test_symbol_defaults(self):
        s = CodeSymbol(name="x", kind=SymbolKind.VARIABLE, line=1)
        assert s.docstring == ""
        assert s.signature == ""


class TestCodingSession:
    def test_create_session(self):
        s = CodingSession(id="s1", goal="Test session", user_id="u1", status=SessionStatus.ACTIVE)
        assert s.id == "s1"
        assert s.goal == "Test session"
        assert s.user_id == "u1"
        assert s.status == SessionStatus.ACTIVE

    def test_session_defaults(self):
        s = CodingSession(id="s2", goal="fix bug", user_id="u1")
        assert s.status == SessionStatus.ACTIVE
        assert s.files == []


class TestReviewComment:
    def test_create_comment(self):
        c = ReviewComment(file="test.py", line=10, severity=ReviewSeverity.WARNING, message="Bad", suggestion="Fix it")
        assert c.file == "test.py"
        assert c.line == 10
        assert c.severity == ReviewSeverity.WARNING
        assert c.message == "Bad"

    def test_comment_defaults(self):
        c = ReviewComment()
        assert c.file == ""
        assert c.severity == ReviewSeverity.WARNING


class TestCodeIndexer:
    def test_index_simple_python(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "hello.py").write_text("def greet(name):\n    return f'Hello {name}'\n\nx = 1\n")
        indexer = CodeIndexer(str(src))
        files = indexer.index()
        assert len(files) == 1
        key = list(files.keys())[0]
        assert "hello.py" in key

    def test_index_empty_dir(self, tmp_path):
        indexer = CodeIndexer(str(tmp_path))
        files = indexer.index()
        assert files == {}

    def test_search(self, tmp_path):
        (tmp_path / "search_test.py").write_text("def search_func():\n    pass\n")
        indexer = CodeIndexer(str(tmp_path))
        indexer.index()
        results = indexer.search("search_func")
        assert len(results) > 0
        assert any("search_test" in r.path for r in results)

    def test_search_no_results(self, tmp_path):
        indexer = CodeIndexer(str(tmp_path))
        indexer.index()
        results = indexer.search("nonexistent_symbol_xyz")
        assert len(results) == 0

    def test_summary(self, tmp_path):
        (tmp_path / "sum.py").write_text("class A:\n    pass\n")
        indexer = CodeIndexer(str(tmp_path))
        indexer.index()
        summary = indexer.summary()
        assert "files" in summary
        assert summary["files"] >= 1

    def test_index_nonexistent_dir(self):
        indexer = CodeIndexer("\\\\nonexistent\\\\path")
        files = indexer.index()
        assert files == {}

    def test_get_file(self, tmp_path):
        (tmp_path / "get.py").write_text("x = 1")
        indexer = CodeIndexer(str(tmp_path))
        indexer.index()
        cf = indexer.get_file("get.py")
        assert cf is not None
        assert cf.path == "get.py"


class TestCodeReviewer:
    @pytest.mark.asyncio
    async def test_review_syntax_error(self, tmp_path):
        f = tmp_path / "syntax_err.py"
        content = "def broken(\n    pass\n"
        f.write_text(content)
        reviewer = CodeReviewer()
        comments = await reviewer.review_file(str(f), content, language="python")
        assert len(comments) >= 0

    @pytest.mark.asyncio
    async def test_review_clean_file(self, tmp_path):
        content = "def foo():\n    return 1\n"
        reviewer = CodeReviewer()
        comments = await reviewer.review_file("clean.py", content, language="python")
        assert isinstance(comments, list)

    @pytest.mark.asyncio
    async def test_review_wildcard_import(self, tmp_path):
        content = "from os import *\n"
        reviewer = CodeReviewer()
        comments = await reviewer.review_file("wild.py", content, language="python")
        assert any("wildcard" in c.message.lower() for c in comments)

    @pytest.mark.asyncio
    async def test_review_todo(self, tmp_path):
        content = "# TODO: fix this later\nx = 1\n"
        reviewer = CodeReviewer()
        comments = await reviewer.review_file("todo_file.py", content, language="python")
        assert any("todo" in c.message.lower() for c in comments)

    @pytest.mark.asyncio
    async def test_review_empty_file(self, tmp_path):
        reviewer = CodeReviewer()
        comments = await reviewer.review_file("empty.py", "")
        assert isinstance(comments, list)

    @pytest.mark.asyncio
    async def test_review_python_specific(self):
        content = "except:\n    pass\n"
        reviewer = CodeReviewer()
        comments = await reviewer.review_file("test.py", content, language="python")
        assert any("bare except" in c.message.lower() for c in comments)

    @pytest.mark.asyncio
    async def test_review_diff(self):
        diff = "+line with trailing whitespace \n-normal line\n"
        reviewer = CodeReviewer()
        comments = await reviewer.review_diff(diff)
        assert isinstance(comments, list)


class TestCodingSessionManager:
    @pytest.mark.asyncio
    async def test_create_and_get_session(self, tmp_path):
        db_path = str(tmp_path / "coder_test.db")
        manager = CodingSessionManager(db_path)
        session = CodingSession(goal="test goal", user_id="u1")
        saved = manager.create_session(session)
        assert saved.id is not None
        assert saved.goal == "test goal"

    @pytest.mark.asyncio
    async def test_list_sessions(self, tmp_path):
        db_path = str(tmp_path / "coder_list.db")
        manager = CodingSessionManager(db_path)
        manager.create_session(CodingSession(goal="goal 1", user_id="u1"))
        sessions = manager.list_sessions()
        assert len(sessions) >= 1

    @pytest.mark.asyncio
    async def test_update_session(self, tmp_path):
        db_path = str(tmp_path / "coder_update.db")
        manager = CodingSessionManager(db_path)
        s = CodingSession(goal="goal to update", user_id="u1")
        manager.create_session(s)
        s.status = SessionStatus.COMPLETED
        manager.update_session(s)
        loaded = manager.get_session(s.id)
        assert loaded is not None
        assert loaded.status == SessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, tmp_path):
        db_path = str(tmp_path / "coder_nonexist.db")
        manager = CodingSessionManager(db_path)
        session = manager.get_session("nonexistent_id")
        assert session is None

    @pytest.mark.asyncio
    async def test_add_history(self, tmp_path):
        db_path = str(tmp_path / "coder_hist.db")
        manager = CodingSessionManager(db_path)
        s = CodingSession(goal="hist test", user_id="u1")
        manager.create_session(s)
        manager.add_history(s.id, "user", "hello")
        loaded = manager.get_session(s.id)
        assert loaded is not None
        assert len(loaded.history) >= 1

    @pytest.mark.asyncio
    async def test_delete_session(self, tmp_path):
        db_path = str(tmp_path / "coder_del.db")
        manager = CodingSessionManager(db_path)
        s = CodingSession(goal="to delete", user_id="u1")
        manager.create_session(s)
        manager.delete_session(s.id)
        assert manager.get_session(s.id) is None

    @pytest.mark.asyncio
    async def test_list_sessions_by_user(self, tmp_path):
        from raven.core.coder.session import _local

        _local.conn = None
        db_path = str(tmp_path / "coder_user.db")
        manager = CodingSessionManager(db_path)
        manager.create_session(CodingSession(goal="user1 goal", user_id="u1"))
        manager.create_session(CodingSession(goal="user2 goal", user_id="u2"))
        u1_sessions = manager.list_sessions(user_id="u1")
        assert len(u1_sessions) == 1
        assert u1_sessions[0].user_id == "u1"

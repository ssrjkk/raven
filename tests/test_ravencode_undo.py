from __future__ import annotations

import tempfile
from pathlib import Path

from ravencode.runtime.undo import UndoEntry, UndoManager, get_undo_manager, record_undo


class TestUndoEntry:
    def test_stores_values(self):
        e = UndoEntry("path.txt", "old", "new", "edit")
        assert e.path == "path.txt"
        assert e.original == "old"
        assert e.modified == "new"
        assert e.tool_name == "edit"


class TestUndoManager:
    def test_can_undo_initial_false(self):
        m = UndoManager()
        assert not m.can_undo
        assert not m.can_redo

    def test_record_adds_to_undo(self):
        m = UndoManager()
        m.record("a.txt", "old", "new", "write")
        assert m.can_undo
        assert not m.can_redo

    def test_record_clears_redo(self):
        m = UndoManager()
        m.record("a.txt", "old", "new", "write")
        m.record("a.txt", "old2", "new2", "write")
        assert not m.can_redo

    def test_undo_returns_none_when_empty(self):
        m = UndoManager()
        assert m.undo() is None

    def test_redo_returns_none_when_empty(self):
        m = UndoManager()
        assert m.redo() is None

    def test_undo_writes_original_back(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("original content")
            path = f.name
        try:
            m = UndoManager()
            m.record(path, "original content", "modified content", "edit")
            result = m.undo()
            assert result is not None
            assert result.startswith("[undo]")
            assert Path(path).read_text(encoding="utf-8") == "original content"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_undo_then_redo(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("original")
            path = f.name
        try:
            m = UndoManager()
            m.record(path, "original", "modified", "edit")
            m.undo()
            result = m.redo()
            assert result is not None
            assert result.startswith("[redo]")
            assert Path(path).read_text(encoding="utf-8") == "modified"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_undo_file_not_found_returns_error(self):
        m = UndoManager()
        m.record("/nonexistent/path.txt", "old", "new", "write")
        result = m.undo()
        assert result is not None
        assert result.startswith("[error]")

    def test_redo_file_not_found_returns_error(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("original")
            path = f.name
        try:
            m = UndoManager()
            m.record(path, "original", "modified", "write")
            m.undo()
            Path(path).unlink()
            result = m.redo()
            assert result is not None
            assert result.startswith("[error]")
        finally:
            Path(path).unlink(missing_ok=True)

    def test_max_entries(self):
        m = UndoManager(max_entries=3)
        for i in range(5):
            m.record(f"{i}.txt", "old", "new", "write")
        assert m.can_undo
        m.undo()
        m.undo()
        m.undo()
        assert not m.can_undo


class TestGlobalFunctions:
    def test_get_undo_manager_singleton(self):
        m1 = get_undo_manager()
        m2 = get_undo_manager()
        assert m1 is m2

    def test_record_undo_creates_entry(self):
        m = get_undo_manager()
        record_undo("/tmp/test.txt", "old", "new", "test")
        assert m.can_undo
        m.undo()

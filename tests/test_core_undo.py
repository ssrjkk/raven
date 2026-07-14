# mypy: ignore-errors
from __future__ import annotations

import pytest


class TestUndo:
    def setup_method(self) -> None:
        from raven.core.undo import get_undo_manager

        self.mgr = get_undo_manager()

    def test_can_undo_initially_false(self) -> None:
        assert self.mgr.can_undo is False

    def test_can_redo_initially_false(self) -> None:
        assert self.mgr.can_redo is False

    def test_record_adds_to_undo_stack(self) -> None:
        self.mgr.record("test.txt", "original", "modified", "edit")
        assert self.mgr.can_undo is True

    def test_undo_clears_redo_on_record(self) -> None:
        self.mgr.record("a.txt", "o1", "m1", "edit1")
        self.mgr.undo()
        assert self.mgr.can_redo is True
        self.mgr.record("b.txt", "o2", "m2", "edit2")
        assert self.mgr.can_redo is False

    def test_undo_writes_original_content(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "test.txt"
        f.write_text("modified")
        self.mgr.record(str(f), "original", "modified", "edit")
        result = self.mgr.undo()
        assert result is not None
        assert "undo" in result
        assert f.read_text() == "original"

    def test_redo_after_undo(self, tmp_path: pytest.TempPathFactory) -> None:
        f = tmp_path / "test.txt"
        f.write_text("modified")
        self.mgr.record(str(f), "original", "modified", "edit")
        self.mgr.undo()
        result = self.mgr.redo()
        assert result is not None
        assert "redo" in result

    def test_max_entries_respected(self) -> None:
        for i in range(120):
            self.mgr.record(f"f{i}.txt", "o", "m", "edit")
        assert self.mgr._undo_stack[-1].path == "f119.txt"
        assert len(self.mgr._undo_stack) <= 100

    @pytest.mark.asyncio
    async def test_undo_none_when_empty(self) -> None:
        from raven.core.undo import get_undo_manager, undo_last

        mgr = get_undo_manager()
        mgr._undo_stack.clear()
        mgr._redo_stack.clear()
        result = await undo_last()
        assert "nothing to undo" in result

    @pytest.mark.asyncio
    async def test_redo_none_when_empty(self) -> None:
        from raven.core.undo import get_undo_manager, redo_last

        mgr = get_undo_manager()
        mgr._undo_stack.clear()
        mgr._redo_stack.clear()
        result = await redo_last()
        assert "nothing to redo" in result

    def test_undo_failed_file_not_found(self) -> None:
        self.mgr.record("/nonexistent/path.txt", "original", "modified", "edit")
        result = self.mgr.undo()
        assert result is not None
        assert "error" in result

    def test_redo_failed_file_not_found(self) -> None:
        self.mgr.record("/nonexistent/path.txt", "original", "modified", "edit")
        self.mgr.undo()
        result = self.mgr.redo()
        assert result is not None
        assert "error" in result

    def test_record_undo_global_function(self, tmp_path: pytest.TempPathFactory) -> None:
        import raven.core.undo as undo_module

        f = tmp_path / "test.txt"
        f.write_text("modified")
        undo_module.record_undo(str(f), "original", "modified", "test_tool")
        assert undo_module.get_undo_manager().can_undo is True

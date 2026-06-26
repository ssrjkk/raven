from __future__ import annotations

from pathlib import Path

from loguru import logger


class UndoEntry:
    def __init__(self, path: str, original: str, modified: str, tool_name: str) -> None:
        self.path = path
        self.original = original
        self.modified = modified
        self.tool_name = tool_name


class UndoManager:
    def __init__(self, max_entries: int = 100) -> None:
        self._undo_stack: list[UndoEntry] = []
        self._redo_stack: list[UndoEntry] = []
        self._max_entries = max_entries

    def record(self, path: str, original: str, modified: str, tool_name: str) -> None:
        self._undo_stack.append(UndoEntry(path, original, modified, tool_name))
        self._redo_stack.clear()
        while len(self._undo_stack) > self._max_entries:
            self._undo_stack.pop(0)

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def _apply(self, entry: UndoEntry) -> str:
        p = Path(entry.path).expanduser().resolve()
        p.write_text(entry.modified, encoding="utf-8")
        logger.info("Undo applied {} on {}", entry.tool_name, entry.path)
        return f"[undo] {entry.tool_name} on {entry.path}"

    def undo(self) -> str | None:
        if not self._undo_stack:
            return None
        entry = self._undo_stack.pop()
        try:
            p = Path(entry.path).expanduser().resolve()
            current = p.read_text(encoding="utf-8")
            self._redo_stack.append(UndoEntry(entry.path, current, entry.original, entry.tool_name))
            result = self._apply(UndoEntry(entry.path, "", entry.original, entry.tool_name))
            return result
        except OSError as exc:
            logger.error("Undo failed: {}", exc)
            return f"[error] undo failed: {exc}"

    def redo(self) -> str | None:
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        try:
            p = Path(entry.path).expanduser().resolve()
            current = p.read_text(encoding="utf-8")
            self._undo_stack.append(UndoEntry(entry.path, current, entry.modified, entry.tool_name))
            result = self._apply(UndoEntry(entry.path, "", entry.modified, entry.tool_name))
            return result
        except OSError as exc:
            logger.error("Redo failed: {}", exc)
            return f"[error] redo failed: {exc}"


_undo_manager: UndoManager | None = None


def get_undo_manager() -> UndoManager:
    global _undo_manager
    if _undo_manager is None:
        _undo_manager = UndoManager()
    return _undo_manager


def record_undo(path: str, original: str, modified: str, tool_name: str) -> None:
    get_undo_manager().record(path, original, modified, tool_name)


async def undo_last() -> str:
    result = get_undo_manager().undo()
    return result or "[undo] nothing to undo"


async def redo_last() -> str:
    result = get_undo_manager().redo()
    return result or "[redo] nothing to redo"

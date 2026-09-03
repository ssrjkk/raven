from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

import ravencode.runtime.todo as todo_mod
from ravencode.runtime.todo import todo_clear, todo_list, todo_update, todo_write


@pytest.fixture(autouse=True)
def reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    todo_mod._TODO_STORE.clear()
    todo_mod._ORDER.clear()
    todo_mod._LOADED = True
    monkeypatch.setattr(todo_mod, "_TODO_PATH", tmp_path / "todo.json")
    yield
    todo_mod._TODO_STORE.clear()
    todo_mod._ORDER.clear()
    todo_mod._LOADED = True


class TestTodoWrite:
    def test_write_tasks(self) -> None:
        result = todo_write([{"content": "one"}, {"content": "two"}])
        assert result == "  [pending] 1: one\n  [pending] 2: two"

    def test_write_empty(self) -> None:
        assert todo_write([]) == "(empty todo list)"

    def test_explicit_ids_preserve_order(self) -> None:
        todo_write([{"id": "b", "content": "B"}, {"id": "a", "content": "A"}])
        todo_write([{"id": "a", "content": "A2"}, {"id": "c", "content": "C"}])
        assert todo_list() == "  [pending] b: B\n  [pending] a: A2\n  [pending] c: C\n\nProgress: 0/3 completed, 0 in progress"

    def test_status_field(self) -> None:
        result = todo_write([{"id": "x", "content": "X", "status": "completed"}])
        assert result == "  [completed] x: X"


class TestTodoList:
    def test_empty(self) -> None:
        assert todo_list() == "(empty todo list)"

    def test_filter(self) -> None:
        todo_write([{"id": "a", "content": "A", "status": "completed"}, {"id": "b", "content": "B"}])
        assert todo_list("completed") == "  [completed] a: A\n\nProgress: 1/2 completed, 0 in progress"
        assert todo_list("in_progress") == "(empty todo list)"

    def test_missing_store_entry_skipped(self, monkeypatch) -> None:
        todo_write([{"id": "a", "content": "A"}])
        todo_mod._TODO_STORE.pop("a")
        assert todo_list() == "(empty todo list)"


class TestTodoUpdate:
    def test_update(self) -> None:
        todo_write([{"id": "a", "content": "A"}])
        result = todo_update("a", "completed")
        assert result == "[completed] a: A\nProgress: 1/1 completed, 0 in progress"

    def test_update_missing(self) -> None:
        assert todo_update("nope") == "[error] todo nope not found"

    def test_update_default_status(self) -> None:
        todo_write([{"id": "a", "content": "A", "status": "completed"}])
        result = todo_update("a")
        assert result.startswith("[pending] a: A")


class TestTodoClear:
    def test_clear(self) -> None:
        todo_write([{"id": "a", "content": "A"}])
        todo_clear()
        assert todo_list() == "(empty todo list)"

    def test_reset_state(self) -> None:
        todo_write([{"id": "a", "content": "A"}])
        todo_mod._reset_state()
        assert todo_list() == "(empty todo list)"


class TestTodoPersistence:
    def test_persists_across_reload(self) -> None:
        todo_write([{"id": "a", "content": "persisted", "status": "completed"}])
        todo_mod._reset_state()
        todo_mod._LOADED = False
        assert todo_list() == "  [completed] a: persisted\n\nProgress: 1/1 completed, 0 in progress"

    def test_clear_persists_empty(self) -> None:
        todo_write([{"id": "a", "content": "A"}])
        todo_clear()
        todo_mod._LOADED = False
        assert todo_list() == "(empty todo list)"

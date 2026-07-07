from __future__ import annotations

from ravencode.runtime.todo import todo_clear, todo_list, todo_update, todo_write
from ravencode.runtime.todo import _reset_state


def _setup():
    _reset_state()


class TestTodoWrite:
    def test_write_single_task(self):
        _setup()
        result = todo_write([{"content": "do something"}])
        assert "1" in result

    def test_write_multiple_tasks(self):
        _setup()
        result = todo_write([
            {"content": "task 1"},
            {"content": "task 2"},
        ])
        assert "1" in result
        assert "2" in result

    def test_write_with_custom_id(self):
        _setup()
        result = todo_write([{"id": "myid", "content": "custom id task"}])
        assert "myid" in result

    def test_write_with_status(self):
        _setup()
        result = todo_write([{"content": "in progress", "status": "in_progress"}])
        assert "in_progress" in result


class TestTodoList:
    def test_list_empty(self):
        _setup()
        assert todo_list() == "(empty todo list)"

    def test_list_with_tasks(self):
        _setup()
        todo_write([{"content": "task A"}, {"content": "task B"}])
        result = todo_list()
        assert "task A" in result
        assert "task B" in result

    def test_list_filtered_by_status(self):
        _setup()
        todo_write([{"content": "pending task"}, {"content": "done task", "status": "completed"}])
        pending = todo_list("pending")
        assert "pending task" in pending
        assert "done task" not in pending
        completed = todo_list("completed")
        assert "done task" in completed
        assert "pending task" not in completed

    def test_list_filter_no_match(self):
        _setup()
        todo_write([{"content": "task"}])
        result = todo_list("cancelled")
        assert result == "(empty todo list)"


class TestTodoUpdate:
    def test_update_status(self):
        _setup()
        todo_write([{"id": "t1", "content": "task"}])
        result = todo_update("t1", "completed")
        assert "completed" in result
        assert "t1" in result

    def test_update_nonexistent(self):
        _setup()
        result = todo_update("nope", "completed")
        assert "not found" in result

    def test_update_invalid_status(self):
        _setup()
        todo_write([{"id": "t1", "content": "task"}])
        result = todo_update("t1", "invalid")
        assert "invalid" in result


class TestTodoClear:
    def test_clears_all(self):
        _setup()
        todo_write([{"content": "task"}])
        todo_clear()
        assert todo_list() == "(empty todo list)"

    def test_clear_empty(self):
        _setup()
        todo_clear()
        assert todo_list() == "(empty todo list)"

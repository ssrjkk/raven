from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from raven.core.task_queue import Task, TaskQueue, TaskStatus


class TestTask:
    def test_create(self):
        t = Task(id="abc", name="test", payload={"x": 1})
        assert t.id == "abc"
        assert t.name == "test"
        assert t.payload == {"x": 1}
        assert t.status == TaskStatus.PENDING

    def test_to_dict(self):
        t = Task(id="abc", name="test", payload={"x": 1})
        d = t.to_dict()
        assert d["id"] == "abc"
        assert json.loads(d["payload"]) == {"x": 1}
        assert d["status"] == "pending"

    def test_from_dict(self):
        d = {"id": "abc", "name": "test", "payload": '{"x": 1}', "status": "running", "result": "ok", "error": ""}
        t = Task.from_dict(d)
        assert t.id == "abc"
        assert t.payload == {"x": 1}
        assert t.status == TaskStatus.RUNNING
        assert t.result == "ok"

    def test_status_done(self):
        t = Task(id="a", name="t", payload={}, status=TaskStatus.DONE)
        assert t.status == TaskStatus.DONE


class MockDB:
    def __init__(self):
        self.store = {}

    async def save_plugin_state(self, plugin_id, key, value):
        self.store[(plugin_id, key)] = value

    async def get_plugin_state(self, plugin_id, key):
        return self.store.get((plugin_id, key))


class TestTaskQueue:
    @pytest.mark.asyncio
    async def test_enqueue(self):
        db = MockDB()
        q = TaskQueue(db)  # type: ignore[arg-type]
        task = await q.enqueue("test", {"x": 1})
        assert task.name == "test"
        assert task.payload == {"x": 1}
        assert task.status == TaskStatus.PENDING
        assert ("task_queue", task.id) in db.store

    @pytest.mark.asyncio
    async def test_register_and_run(self):
        db = MockDB()
        q = TaskQueue(db, max_concurrent=1)  # type: ignore[arg-type]

        handler = AsyncMock(return_value="done")
        q.register("test_job", handler)

        await q.enqueue("test_job", {"key": "val"})
        await q.start()
        await asyncio.sleep(0.05)
        await q.stop()

        assert handler.called
        call_kwargs = handler.call_args[1]
        assert call_kwargs.get("key") == "val"

    @pytest.mark.asyncio
    async def test_no_handler(self):
        db = MockDB()
        q = TaskQueue(db, max_concurrent=1)  # type: ignore[arg-type]
        task = await q.enqueue("nonexistent")
        await q.start()
        await asyncio.sleep(0.05)
        await q.stop()

        stored = await q.get_task(task.id)
        assert stored is not None
        assert stored.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_cancel_pending(self):
        db = MockDB()
        q = TaskQueue(db)  # type: ignore[arg-type]
        task = await q.enqueue("test")
        cancelled = await q.cancel(task.id)
        assert cancelled

        stored = await q.get_task(task.id)
        assert stored.status == TaskStatus.CANCELLED  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self):
        db = MockDB()
        q = TaskQueue(db)  # type: ignore[arg-type]
        cancelled = await q.cancel("no_such_task")
        assert not cancelled

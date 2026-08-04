from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.task_engine.models import Task, TaskStatus, TaskStep
from raven.core.task_engine.store import TaskStore
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def _async_gen(items):
    for item in items:
        yield item


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "tasks.db")


@pytest.fixture
async def store(db_path: str):
    s = TaskStore(db_path)
    yield s
    await s.close()


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(
        ToolSpec(
            name="web_search",
            description="Search the web",
            parameters={"query": {"type": "string"}},
            handler=AsyncMock(return_value="search results"),
        )
    )
    r.register(
        ToolSpec(
            name="get_weather",
            description="Get weather for location",
            parameters={"location": {"type": "string"}},
            handler=AsyncMock(return_value="sunny 25C"),
        )
    )
    r.register(
        ToolSpec(
            name="slow_tool",
            description="Slow tool for timeout testing",
            parameters={},
            handler=AsyncMock(side_effect=lambda: asyncio.sleep(3600)),
            timeout=1,
        )
    )
    return r


@pytest.fixture
def task() -> Task:
    t = Task(
        goal="test task",
        plan_summary="a simple test",
        status=TaskStatus.PENDING,
        steps=[
            TaskStep(task_id="", order=0, description="search web", tool="web_search", params={"query": "test"}),
            TaskStep(task_id="", order=1, description="get weather", tool="get_weather", params={"location": "London"}),
        ],
    )
    for s in t.steps:
        s.task_id = t.id
    return t


class TestToolRegistry:
    def test_register_and_get(self, registry: ToolRegistry):
        spec = registry.get("web_search")
        assert spec is not None
        assert spec.name == "web_search"
        assert spec.description == "Search the web"

    def test_unregister(self, registry: ToolRegistry):
        registry.unregister("web_search")
        assert registry.get("web_search") is None

    def test_list(self, registry: ToolRegistry):
        tools = registry.list()
        names = [t.name for t in tools]
        assert "web_search" in names
        assert "get_weather" in names

    def test_list_by_category(self, registry: ToolRegistry):
        tools = registry.list(category="general")
        assert len(tools) == 3

    async def test_call_success(self, registry: ToolRegistry):
        result = await registry.call("web_search", query="hello")
        assert result == "search results"

    async def test_call_unknown(self, registry: ToolRegistry):
        result = await registry.call("nonexistent")
        assert "Unknown tool" in result

    def test_to_llm_tools(self, registry: ToolRegistry):
        tools = registry.to_llm_tools()
        assert len(tools) == 3
        assert tools[0]["type"] == "function"
        assert "function" in tools[0]

    def test_count(self, registry: ToolRegistry):
        assert registry.count == 3


class TestTaskStore:
    @pytest.mark.asyncio
    async def test_save_and_load(self, store: TaskStore, task: Task):
        await store.save_task(task)
        loaded = await store.load_task(task.id)
        assert loaded is not None
        assert loaded.goal == "test task"
        assert len(loaded.steps) == 2
        assert loaded.steps[0].tool == "web_search"

    @pytest.mark.asyncio
    async def test_list_tasks(self, store: TaskStore, task: Task):
        await store.save_task(task)
        tasks = await store.list_tasks()
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_list_tasks_by_user(self, store: TaskStore):
        a = Task(goal="task1", user_id="u1")
        b = Task(goal="task2", user_id="u2")
        await store.save_task(a)
        await store.save_task(b)
        u1_tasks = await store.list_tasks(user_id="u1")
        assert len(u1_tasks) == 1

    @pytest.mark.asyncio
    async def test_update_status(self, store: TaskStore, task: Task):
        await store.save_task(task)
        await store.update_status(task.id, TaskStatus.RUNNING)
        loaded = await store.load_task(task.id)
        assert loaded is not None
        assert loaded.status == TaskStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_status_with_error(self, store: TaskStore, task: Task):
        await store.save_task(task)
        await store.update_status(task.id, TaskStatus.FAILED, error="something broke")
        loaded = await store.load_task(task.id)
        assert loaded is not None
        assert loaded.status == TaskStatus.FAILED
        assert loaded.error == "something broke"

    @pytest.mark.asyncio
    async def test_delete(self, store: TaskStore, task: Task):
        await store.save_task(task)
        await store.delete_task(task.id)
        loaded = await store.load_task(task.id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_count_tasks(self, store: TaskStore):
        await store.save_task(Task(goal="a"))
        await store.save_task(Task(goal="b"))
        assert await store.count_tasks() == 2


class TestTaskPlanner:
    @patch("raven.core.task_engine.planner.LLMRouter")
    async def test_plan_parses_response(self, mock_llm_cls):
        mock_llm = MagicMock()
        mock_llm.complete_stream = lambda messages, model=None, tools=None: _async_gen(
            [
                '{"summary": "test plan", "steps": [{"description": "search", "tool": "web_search", "params": {"query": "x"}}]}'
            ]
        )
        from raven.core.task_engine.planner import TaskPlanner

        planner = TaskPlanner(ToolRegistry())
        task = await planner.plan("test goal", mock_llm)
        assert task.goal == "test goal"
        assert task.plan_summary == "test plan"
        assert len(task.steps) == 1
        assert task.steps[0].tool == "web_search"

    @patch("raven.core.task_engine.planner.LLMRouter")
    async def test_plan_fallback_on_bad_json(self, mock_llm_cls):
        mock_llm = MagicMock()
        mock_llm.complete_stream = lambda messages, model=None, tools=None: _async_gen(["garbage response"])
        from raven.core.task_engine.planner import TaskPlanner

        planner = TaskPlanner(ToolRegistry())
        task = await planner.plan("test", mock_llm)
        assert task.steps == []


class TestTaskRunner:
    async def test_submit_and_complete(self, store: TaskStore, registry: ToolRegistry, task: Task):
        from raven.core.task_engine.runner import TaskRunner

        runner = TaskRunner(store, registry)
        result = await runner.submit(task)
        assert result.status == TaskStatus.PENDING

        completed = await runner.wait(task.id, timeout=10)
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED
        assert len(completed.steps) == 2
        assert completed.steps[0].status == TaskStatus.COMPLETED
        assert completed.steps[1].status == TaskStatus.COMPLETED

    async def test_cancel(self, store: TaskStore, registry: ToolRegistry, task: Task):
        from raven.core.task_engine.runner import TaskRunner

        runner = TaskRunner(store, registry)
        await runner.submit(task)

        cancelled = await runner.cancel(task.id)
        assert cancelled is True

        completed = await runner.wait(task.id, timeout=10)
        assert completed is not None
        assert completed.status == TaskStatus.CANCELLED

    async def test_cancel_nonexistent(self, store: TaskStore, registry: ToolRegistry):
        from raven.core.task_engine.runner import TaskRunner

        runner = TaskRunner(store, registry)
        cancelled = await runner.cancel("nonexistent")
        assert cancelled is False

    async def test_pause_resume(self, store: TaskStore, registry: ToolRegistry):
        from raven.core.task_engine.runner import TaskRunner

        t = Task(
            goal="pause test",
            steps=[TaskStep(task_id="", order=0, description="slow", tool="slow_tool", params={})],
        )
        for s in t.steps:
            s.task_id = t.id
        await store.save_task(t)
        await store.update_status(t.id, TaskStatus.RUNNING)

        runner = TaskRunner(store, registry)
        paused = await runner.pause(t.id)
        assert paused is True

    async def test_list_tasks(self, store: TaskStore, registry: ToolRegistry, task: Task):
        from raven.core.task_engine.runner import TaskRunner

        runner = TaskRunner(store, registry)
        await store.save_task(task)
        tasks = await runner.list_tasks()
        assert len(tasks) >= 1

    async def test_get_task(self, store: TaskStore, registry: ToolRegistry, task: Task):
        from raven.core.task_engine.runner import TaskRunner

        runner = TaskRunner(store, registry)
        await store.save_task(task)
        loaded = await runner.get_task(task.id)
        assert loaded is not None
        assert loaded.goal == "test task"

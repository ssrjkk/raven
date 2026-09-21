from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from raven.core.agents.scheduler import TaskScheduler


@dataclass
class T:
    name: str
    depends_on: list[int] = field(default_factory=list)


@pytest.mark.asyncio
async def test_sequential_order():
    order: list[int] = []

    async def executor(i: int, t: T) -> str:
        order.append(i)
        return t.name

    results = await TaskScheduler(executor).run_sequential([T("a"), T("b"), T("c")])
    assert results == ["a", "b", "c"]
    assert order == [0, 1, 2]


@pytest.mark.asyncio
async def test_parallel_bounded_concurrency():
    running = 0
    peak = 0

    async def executor(i: int, t: T) -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return i

    results = await TaskScheduler(executor, max_concurrent=2).run_parallel([T(str(i)) for i in range(6)])
    assert sorted(results) == list(range(6))
    assert peak <= 2


@pytest.mark.asyncio
async def test_parallel_per_call_max_concurrent():
    running = 0
    peak = 0

    async def executor(i: int, t: T) -> int:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return i

    await TaskScheduler(executor, max_concurrent=10).run_parallel([T(str(i)) for i in range(4)], max_concurrent=1)
    assert peak == 1


@pytest.mark.asyncio
async def test_dag_respects_dependencies():
    started: list[int] = []

    async def executor(i: int, t: T) -> int:
        started.append(i)
        return i

    tasks = [T("root"), T("mid", depends_on=[0]), T("leaf", depends_on=[1]), T("free")]
    results = await TaskScheduler(executor, depends_on=lambda t: t.depends_on).run_dag(tasks)
    assert results == [0, 1, 2, 3]
    assert started.index(0) < started.index(1) < started.index(2)


@pytest.mark.asyncio
async def test_dag_circular_dependency():
    async def executor(i: int, t: T) -> int:
        return i

    tasks = [T("a", depends_on=[1]), T("b", depends_on=[0])]
    with pytest.raises(RuntimeError, match="Circular dependency"):
        await TaskScheduler(executor, depends_on=lambda t: t.depends_on).run_dag(tasks)


@pytest.mark.asyncio
async def test_dag_empty():
    async def executor(i: int, t: T) -> int:
        return i

    assert await TaskScheduler(executor).run_dag([]) == []

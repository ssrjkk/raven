from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class TaskScheduler(Generic[T, R]):
    """Dependency-aware task scheduler: sequential, bounded-parallel, and DAG modes.

    Generic over task type T and result type R; the executor receives the task
    index and must return the result (index stamping is the caller's concern).
    """

    def __init__(
        self,
        executor: Callable[[int, T], Awaitable[R]],
        max_concurrent: int = 3,
        depends_on: Callable[[T], list[int]] | None = None,
    ) -> None:
        self._executor = executor
        self._max_concurrent = max_concurrent
        self._depends_on = depends_on or (lambda _t: [])

    async def run_sequential(self, tasks: Sequence[T]) -> list[R]:
        return [await self._executor(i, t) for i, t in enumerate(tasks)]

    async def run_parallel(self, tasks: Sequence[T], max_concurrent: int | None = None) -> list[R]:
        sem = asyncio.Semaphore(max_concurrent or self._max_concurrent)
        results: list[R | None] = [None] * len(tasks)

        async def run_one(i: int, task: T) -> None:
            async with sem:
                results[i] = await self._executor(i, task)

        await asyncio.gather(*[run_one(i, t) for i, t in enumerate(tasks)])
        return [r for r in results if r is not None]

    async def run_dag(self, tasks: Sequence[T], max_concurrent: int | None = None) -> list[R]:
        sem = asyncio.Semaphore(max_concurrent or self._max_concurrent)
        results: dict[int, R] = {}
        completed: set[int] = set()
        remaining = list(range(len(tasks)))

        while remaining:
            batch: list[int] = []
            for i in remaining[:]:
                if all(d in completed for d in self._depends_on(tasks[i])):
                    batch.append(i)
                    remaining.remove(i)
            if not batch:
                raise RuntimeError(f"Circular dependency detected among tasks: {remaining}")

            async def run_task(idx: int) -> None:
                async with sem:
                    results[idx] = await self._executor(idx, tasks[idx])

            await asyncio.gather(*[run_task(i) for i in batch])
            completed.update(batch)
        return [results[i] for i in range(len(tasks))]

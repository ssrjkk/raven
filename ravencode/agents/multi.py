"""Multi-agent orchestration — coordinate multiple agents on one task."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger

from ravencode.agents.orchestrator import AgentResult, AgentType, Orchestrator
from ravencode.runtime.agent_core import AgentConfig


@dataclass
class SubTask:
    description: str
    agent_type: AgentType = AgentType.AUTONOMOUS
    depends_on: list[int] | None = None
    config: AgentConfig | None = None


@dataclass
class TaskResult:
    index: int
    description: str
    result: AgentResult
    duration: float


class MultiAgentOrchestrator:
    def __init__(self) -> None:
        self._orchestrator = Orchestrator()

    async def run_sequential(self, tasks: list[SubTask]) -> list[TaskResult]:
        results: list[TaskResult] = []
        for i, task in enumerate(tasks):
            logger.info("Multi-agent: running task {}/{}: {}", i + 1, len(tasks), task.description[:80])
            start = asyncio.get_event_loop().time()
            result = await self._orchestrator.dispatch(
                task.description, task.agent_type, agent_config_override=task.config
            )
            duration = asyncio.get_event_loop().time() - start
            results.append(TaskResult(index=i, description=task.description, result=result, duration=duration))
        return results

    async def run_parallel(self, tasks: list[SubTask], max_concurrent: int = 3) -> list[TaskResult]:
        sem = asyncio.Semaphore(max_concurrent)
        results: list[TaskResult | None] = [None] * len(tasks)

        async def run_one(i: int, task: SubTask) -> None:
            async with sem:
                logger.info("Multi-agent: parallel task {}/{}: {}", i + 1, len(tasks), task.description[:80])
                start = asyncio.get_event_loop().time()
                result = await self._orchestrator.dispatch(
                    task.description, task.agent_type, agent_config_override=task.config
                )
                duration = asyncio.get_event_loop().time() - start
                results[i] = TaskResult(index=i, description=task.description, result=result, duration=duration)

        coros = [run_one(i, t) for i, t in enumerate(tasks)]
        await asyncio.gather(*coros)
        return [r for r in results if r is not None]

    async def run_dag(self, tasks: list[SubTask], max_concurrent: int = 5) -> list[TaskResult]:
        sem = asyncio.Semaphore(max_concurrent)
        results: dict[int, TaskResult] = {}
        completed = set()
        remaining = list(range(len(tasks)))

        while remaining:
            batch = []
            for i in remaining[:]:
                task = tasks[i]
                deps = task.depends_on or []
                if all(d in completed for d in deps):
                    batch.append(i)
                    remaining.remove(i)
            if not batch:
                msg = f"Circular dependency detected among tasks: {remaining}"
                raise RuntimeError(msg)
            coros = []
            for i in batch:
                task = tasks[i]
                logger.info("Multi-agent: DAG task {}/{}: {}", i + 1, len(tasks), task.description[:80])
                t_start = asyncio.get_event_loop().time()

                async def run_task(idx: int, t: SubTask, started: float) -> TaskResult:
                    async with sem:
                        r = await self._orchestrator.dispatch(
                            t.description, t.agent_type, agent_config_override=t.config
                        )
                        dur = asyncio.get_event_loop().time() - started
                        return TaskResult(index=idx, description=t.description, result=r, duration=dur)

                coros.append(run_task(i, task, t_start))
            for r in await asyncio.gather(*coros):
                results[r.index] = r
                completed.add(r.index)
        return [results[i] for i in range(len(tasks))]


_orchestrator_instance: MultiAgentOrchestrator | None = None


def get_multi_orchestrator() -> MultiAgentOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = MultiAgentOrchestrator()
    return _orchestrator_instance

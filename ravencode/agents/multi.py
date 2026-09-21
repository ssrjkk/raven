"""Multi-agent orchestration — coordinate multiple agents on one task."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger

from raven.core.agents.scheduler import TaskScheduler
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

    def _scheduler(self, tasks: list[SubTask], mode: str) -> TaskScheduler[SubTask, TaskResult]:
        total = len(tasks)

        async def executor(i: int, task: SubTask) -> TaskResult:
            logger.info("Multi-agent: {} task {}/{}: {}", mode, i + 1, total, task.description[:80])
            start = asyncio.get_event_loop().time()
            result = await self._orchestrator.dispatch(
                task.description, task.agent_type, agent_config_override=task.config
            )
            duration = asyncio.get_event_loop().time() - start
            return TaskResult(index=i, description=task.description, result=result, duration=duration)

        return TaskScheduler(executor, depends_on=lambda t: t.depends_on or [])

    async def run_sequential(self, tasks: list[SubTask]) -> list[TaskResult]:
        return await self._scheduler(tasks, "sequential").run_sequential(tasks)

    async def run_parallel(self, tasks: list[SubTask], max_concurrent: int = 3) -> list[TaskResult]:
        return await self._scheduler(tasks, "parallel").run_parallel(tasks, max_concurrent=max_concurrent)

    async def run_dag(self, tasks: list[SubTask], max_concurrent: int = 5) -> list[TaskResult]:
        return await self._scheduler(tasks, "DAG").run_dag(tasks, max_concurrent=max_concurrent)


_orchestrator_instance: MultiAgentOrchestrator | None = None


def get_multi_orchestrator() -> MultiAgentOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = MultiAgentOrchestrator()
    return _orchestrator_instance

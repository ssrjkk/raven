from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.agents.orchestrator import AgentOrchestrator, AgentResult
from raven.core.agents.router import FeedbackLoop, get_feedback_loop
from raven.core.features import FeatureFlags

if TYPE_CHECKING:
    from raven.core.llm import LLMRouter
    from raven.core.task_engine.tool_registry import ToolRegistry


@dataclass
class DelegatedTask:
    description: str
    profile: str
    context: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] | None = None


@dataclass
class DelegationResult:
    index: int
    description: str
    profile: str
    content: str
    success: bool
    duration: float
    iterations: int
    tokens_used: int
    handoffs: int


async def delegate(
    query: str,
    llm: LLMRouter,
    tool_registry: ToolRegistry,
    profile_override: str | None = None,
    context: dict[str, Any] | None = None,
    send_fn: Callable[..., Any] | None = None,
) -> AgentResult:
    if not FeatureFlags.get().is_enabled("delegation"):
        logger.info("[delegate] delegation disabled, routing to coder")
        profile_override = "coder"
    orchestrator = AgentOrchestrator(llm=llm, tool_registry=tool_registry, send_fn=send_fn)
    return await orchestrator.execute(
        query=query,
        context=context,
        profile_override=profile_override,
    )


def route_to_profile(query: str, feedback: FeedbackLoop | None = None) -> str:
    keyword_rules: list[tuple[str, str]] = [
        (r"security|vulnerability|cve|owasp|threat|exploit|injection|xss|ssrf|hardcoded|audit", "security"),
        (r"design|architect|architecture|structure|overview|diagram|system design", "architect"),
        (r"plan|break down|decompose|roadmap|milestone|task list", "planner"),
        (r"debug|bug|error|crash|exception|stack trace|not working|broken|failing", "debugger"),
        (r"review|check code|quality|lint|code review|static analysis", "reviewer"),
        (r"test|coverage|unit test|integration test|pytest", "qa"),
        (r"implement|write code|create|refactor|add feature", "coder"),
        (r"research|investigate|explore|find|search|look up|learn|discover", "researcher"),
    ]
    q = query.lower()
    best: tuple[str, float] | None = None
    for pattern, profile in keyword_rules:
        if re.search(pattern, q):
            score = 0.75
            if feedback:
                score = feedback.get_adjusted_confidence(profile, score, query)
            if best is None or score > best[1]:
                best = (profile, score)
    return best[0] if best else "coder"


class DelegationOrchestrator:
    def __init__(
        self,
        llm: LLMRouter,
        tool_registry: ToolRegistry,
        send_fn: Callable[..., Any] | None = None,
        max_concurrent: int = 3,
        max_total_iterations: int = 100,
    ):
        self._llm = llm
        self._tool_registry = tool_registry
        self._send_fn = send_fn
        self._max_concurrent = max_concurrent
        self._max_total_iterations = max_total_iterations

    async def run_sequential(self, tasks: list[DelegatedTask]) -> list[DelegationResult]:
        results: list[DelegationResult] = []
        for i, task in enumerate(tasks):
            logger.info("[delegation] sequential task {}/{}: {} → {}", i + 1, len(tasks), task.description[:80], task.profile)
            result = await self._run_single(task)
            result.index = i
            results.append(result)
        return results

    async def run_parallel(self, tasks: list[DelegatedTask]) -> list[DelegationResult]:
        sem = asyncio.Semaphore(self._max_concurrent)
        results: list[DelegationResult | None] = [None] * len(tasks)

        async def run_one(i: int, task: DelegatedTask) -> None:
            async with sem:
                logger.info("[delegation] parallel task {}/{}: {} → {}", i + 1, len(tasks), task.description[:80], task.profile)
                result = await self._run_single(task)
                result.index = i
                results[i] = result

        await asyncio.gather(*[run_one(i, t) for i, t in enumerate(tasks)])
        return [r for r in results if r is not None]

    async def run_dag(self, tasks: list[DelegatedTask]) -> list[DelegationResult]:
        sem = asyncio.Semaphore(self._max_concurrent)
        results: dict[int, DelegationResult] = {}
        completed: set[int] = set()
        remaining = list(range(len(tasks)))

        while remaining:
            batch: list[int] = []
            for i in remaining[:]:
                deps = tasks[i].depends_on or []
                if all(d in completed for d in deps):
                    batch.append(i)
                    remaining.remove(i)
            if not batch:
                raise RuntimeError(f"Circular dependency detected among tasks: {remaining}")

            async def run_task(idx: int, task: DelegatedTask) -> DelegationResult:
                async with sem:
                    result = await self._run_single(task)
                    result.index = idx
                    return result

            for r in await asyncio.gather(*[run_task(i, tasks[i]) for i in batch]):
                results[r.index] = r
                completed.add(r.index)
        return [results[i] for i in range(len(tasks))]

    async def _run_single(self, task: DelegatedTask) -> DelegationResult:
        import time
        started = time.monotonic()
        feedback = get_feedback_loop()
        try:
            agent = AgentOrchestrator(
                llm=self._llm,
                tool_registry=self._tool_registry,
                send_fn=self._send_fn,
                max_total_iterations=self._max_total_iterations,
            )
            result = await agent.execute(
                query=task.description,
                context=task.context,
                profile_override=task.profile,
            )
            duration = time.monotonic() - started
            feedback.record(task.description, result.profile, result.success)
            return DelegationResult(
                index=0,
                description=task.description,
                profile=result.profile,
                content=result.content,
                success=result.success,
                duration=duration,
                iterations=result.iterations,
                tokens_used=result.tokens_used,
                handoffs=result.handoffs,
            )
        except Exception as e:
            duration = time.monotonic() - started
            logger.error("[delegation] task failed: {}: {}", task.description[:80], e)
            feedback.record(task.description, task.profile, False)
            return DelegationResult(
                index=0,
                description=task.description,
                profile=task.profile,
                content=f"Error: {e}",
                success=False,
                duration=duration,
                iterations=0,
                tokens_used=0,
                handoffs=0,
            )


_orchestrator_instance: DelegationOrchestrator | None = None


def get_delegation_orchestrator(
    llm: LLMRouter | None = None,
    tool_registry: ToolRegistry | None = None,
    send_fn: Callable[..., Any] | None = None,
) -> DelegationOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None and llm is not None and tool_registry is not None:
        _orchestrator_instance = DelegationOrchestrator(llm=llm, tool_registry=tool_registry, send_fn=send_fn)
    elif _orchestrator_instance is None:
        raise RuntimeError("DelegationOrchestrator not initialized: provide llm and tool_registry on first call")
    return _orchestrator_instance

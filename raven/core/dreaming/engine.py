from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.dreaming.consolidation import consolidate_memories
from raven.core.dreaming.generation import generate_skills
from raven.core.dreaming.patterns import detect_patterns
from raven.core.events import EventBus
from raven.core.features import FeatureFlags
from raven.core.skills import Skill, skills_registry

if TYPE_CHECKING:
    from raven.core.memory.manager import MemoryManager


_IDLE_TIMEOUT = 60.0
_CYCLE_INTERVAL = 300.0


def _now() -> float:
    return time.monotonic()


class DreamEngine:
    def __init__(
        self,
        memory: MemoryManager,
        event_bus: EventBus | None = None,
        idle_timeout: float = _IDLE_TIMEOUT,
        cycle_interval: float = _CYCLE_INTERVAL,
    ):
        self._memory = memory
        self._event_bus = event_bus
        self._idle_timeout = idle_timeout
        self._cycle_interval = cycle_interval
        self._task: asyncio.Task[None] | None = None
        self._last_activity: float = 0.0
        self._running = False
        self._last_cycle_stats: dict[str, Any] | None = None
        self._last_cycle_time: float = 0.0
        self._total_cycles: int = 0

    async def start(self) -> None:
        if not FeatureFlags.get().is_enabled("dreaming"):
            logger.info("[dream] dreaming is disabled by feature flag")
            return
        if self._running:
            return
        self._running = True
        self._last_activity = _now()
        if self._event_bus:
            self._event_bus.subscribe("gateway.message_received", self._on_activity)
            self._event_bus.subscribe("gateway.started", self._on_activity)
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[dream] engine started (idle={}s, cycle={}s)", self._idle_timeout, self._cycle_interval)

    async def stop(self) -> None:
        self._running = False
        if self._event_bus:
            self._event_bus.unsubscribe("gateway.message_received", self._on_activity)
            self._event_bus.unsubscribe("gateway.started", self._on_activity)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("[dream] engine stopped")

    async def _on_activity(self, **data: Any) -> None:
        self._last_activity = _now()

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._cycle_interval)
                if not self._running:
                    break
                idle_for = _now() - self._last_activity
                if idle_for < self._idle_timeout:
                    logger.debug("[dream] skipping cycle (active {:.0f}s ago)", idle_for)
                    continue
                await self._cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.opt(exception=True).error("[dream] cycle failed")

    async def _cycle(self) -> dict[str, Any]:
        logger.info("[dream] starting consolidation cycle")
        stats: dict[str, Any] = {}

        cons = await consolidate_memories(self._memory)
        stats["consolidation"] = cons

        patterns = await detect_patterns(self._memory)
        stats["patterns_detected"] = len(patterns)

        proposals = await generate_skills(self._memory, patterns)
        stats["skills_proposed"] = len(proposals)

        if proposals:
            applied = []
            for p in proposals:
                name = p.get("name", "")
                if name:
                    skill = Skill(name=name, description=p.get("description", ""), instructions=p.get("instructions", ""), source="dream")
                    skills_registry.register_builtin(skill)
                    applied.append(name)
            stats["skills_applied"] = len(applied)
            if applied:
                logger.info("[dream] auto-registered {} skills: {}", len(applied), applied)

        self._last_cycle_stats = stats
        self._last_cycle_time = _now()
        self._total_cycles += 1
        logger.info("[dream] cycle complete: {}", stats)
        return stats

    async def cycle_once(self) -> dict[str, Any]:
        return await self._cycle()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_cycle_stats(self) -> dict[str, Any] | None:
        return self._last_cycle_stats

    @property
    def last_cycle_time(self) -> float:
        return self._last_cycle_time

    @property
    def total_cycles(self) -> int:
        return self._total_cycles

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "total_cycles": self._total_cycles,
            "last_cycle_time": self._last_cycle_time or 0,
            "last_cycle_stats": self._last_cycle_stats,
            "idle_timeout": self._idle_timeout,
            "cycle_interval": self._cycle_interval,
        }


_engine_instance: DreamEngine | None = None


def get_dream_engine(
    memory: MemoryManager | None = None,
    event_bus: EventBus | None = None,
) -> DreamEngine:
    global _engine_instance
    if _engine_instance is None:
        if memory is None:
            raise RuntimeError("DreamEngine not initialized: provide memory on first call")
        _engine_instance = DreamEngine(memory=memory, event_bus=event_bus)
    return _engine_instance

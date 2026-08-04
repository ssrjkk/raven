from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from loguru import logger

HEAL_INTERVAL = 30.0
MAX_RESTART_ATTEMPTS = 3
BACKOFF_BASE = 5.0


class ServiceStatus:
    def __init__(self, name: str):
        self.name = name
        self.last_ok: float = 0.0
        self.failures: int = 0
        self.restart_attempts: int = 0
        self.alive: bool = True

    def record_success(self):
        self.last_ok = time.time()
        self.failures = 0

    def record_failure(self):
        self.failures += 1
        if self.failures >= 3:
            self.alive = False

    @property
    def needs_restart(self) -> bool:
        return not self.alive and self.restart_attempts < MAX_RESTART_ATTEMPTS


class SelfHealer:
    def __init__(self):
        self._services: dict[str, tuple[ServiceStatus, Callable[[], Any], Callable[[], Any], float]] = {}
        self._task: asyncio.Task[None] | None = None

    def register(
        self,
        name: str,
        health_check: Callable[[], Any],
        restart: Callable[[], Any],
        timeout: float = 10.0,
    ):
        self._services[name] = (ServiceStatus(name), health_check, restart, timeout)

    def unregister(self, name: str):
        self._services.pop(name, None)

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info("Self-healer started with {} service(s)", len(self._services))

    async def stop(self):
        if self._task:
            self._task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._task, timeout=5.0)
            self._task = None

    async def _run_check(self, health_check: Callable[[], Any], timeout: float) -> bool:
        if asyncio.iscoroutinefunction(health_check):
            return bool(await asyncio.wait_for(health_check(), timeout=timeout))
        return bool(health_check())

    async def _run_restart(self, restart_fn: Callable[[], Any], timeout: float) -> None:
        if asyncio.iscoroutinefunction(restart_fn):
            await asyncio.wait_for(restart_fn(), timeout=timeout)
        else:
            restart_fn()

    async def _loop(self):
        while True:
            for name, (status, health_check, restart_fn, timeout) in list(self._services.items()):
                try:
                    healthy = await self._run_check(health_check, timeout)
                    if healthy:
                        status.record_success()
                    else:
                        status.record_failure()
                except Exception as e:
                    status.record_failure()
                    logger.warning("Health check failed for {}: {}", name, e)

                if status.needs_restart:
                    status.restart_attempts += 1
                    backoff = BACKOFF_BASE * (2 ** (status.restart_attempts - 1))
                    logger.info(
                        "Restarting {} (attempt {}/{}, backoff {}s)",
                        name,
                        status.restart_attempts,
                        MAX_RESTART_ATTEMPTS,
                        backoff,
                    )
                    try:
                        await self._run_restart(restart_fn, timeout)
                        status.alive = True
                        logger.info("Restart of {} succeeded", name)
                    except Exception as e:
                        logger.error("Restart of {} failed: {}", name, e)

            await asyncio.sleep(HEAL_INTERVAL)

    def status_report(self) -> dict[str, Any]:
        return {
            name: {
                "alive": s.alive,
                "failures": s.failures,
                "restart_attempts": s.restart_attempts,
                "last_ok": s.last_ok,
            }
            for name, (s, _, _, _) in self._services.items()
        }


self_healer = SelfHealer()


def create_self_healer() -> SelfHealer:
    return SelfHealer()

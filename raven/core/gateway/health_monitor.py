from __future__ import annotations

from collections.abc import Awaitable, Callable

from raven.core.health import health
from raven.core.self_heal import self_healer


class HealthMonitor:
    def __init__(
        self,
        db_check: Callable[[], Awaitable[bool]],
        llm_check: Callable[[], Awaitable[bool]],
        db_restart: Callable[[], Awaitable[None]] | None = None,
        llm_restart: Callable[[], Awaitable[None]] | None = None,
    ):
        self._db_check = db_check
        self._llm_check = llm_check
        self._db_restart = db_restart
        self._llm_restart = llm_restart

    def register_checks(self) -> None:
        health.register("database", self._db_check, timeout=3.0, critical=True)
        health.register("llm", self._llm_check, timeout=10.0, critical=False)
        if self._db_restart:
            self_healer.register("database", self._db_check, self._db_restart)
        if self._llm_restart:
            self_healer.register("llm", self._llm_check, self._llm_restart)

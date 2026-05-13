from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from loguru import logger

from raven.core.monitor.alert import AlertDispatcher
from raven.core.monitor.conditions import ConditionEvaluator
from raven.core.monitor.models import ConditionOperator, Monitor, MonitorCheck, MonitorStatus
from raven.core.monitor.store import MonitorStore

MonitorHandler = Callable[[Monitor], Awaitable[dict[str, Any]]]


class MonitorEngine:
    def __init__(self, store: MonitorStore, alert_dispatcher: AlertDispatcher | None = None):
        self._store = store
        self._evaluator = ConditionEvaluator()
        self._alerts = alert_dispatcher or AlertDispatcher()
        self._handlers: dict[str, MonitorHandler] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def register_handler(self, monitor_type: str, handler: MonitorHandler) -> None:
        self._handlers[monitor_type] = handler

    async def start(self) -> None:
        self._running = True
        monitors = self._store.list_active()
        for m in monitors:
            self._schedule_monitor(m)
        logger.info("Monitor engine started with {} monitors", len(monitors))

    async def stop(self) -> None:
        self._running = False
        for tid, task in self._tasks.items():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("Monitor engine stopped")

    def add_monitor(self, monitor: Monitor) -> None:
        self._store.save_monitor(monitor)
        if monitor.status == MonitorStatus.ACTIVE:
            self._schedule_monitor(monitor)

    def remove_monitor(self, monitor_id: str) -> None:
        task = self._tasks.pop(monitor_id, None)
        if task:
            task.cancel()
        self._store.delete_monitor(monitor_id)

    def pause_monitor(self, monitor_id: str) -> bool:
        task = self._tasks.pop(monitor_id, None)
        if task:
            task.cancel()
        self._store.update_status(monitor_id, MonitorStatus.PAUSED)
        return True

    def resume_monitor(self, monitor_id: str) -> bool:
        self._store.update_status(monitor_id, MonitorStatus.ACTIVE)
        monitor = self._store.load_monitor(monitor_id)
        if monitor:
            self._schedule_monitor(monitor)
            return True
        return False

    def get_monitor(self, monitor_id: str) -> Monitor | None:
        return self._store.load_monitor(monitor_id)

    def list_monitors(self, user_id: str | None = None) -> list[Monitor]:
        return self._store.list_monitors(user_id=user_id)

    def get_checks(self, monitor_id: str, limit: int = 50) -> list[MonitorCheck]:
        return self._store.get_checks(monitor_id, limit=limit)

    def _schedule_monitor(self, monitor: Monitor) -> None:
        task = asyncio.create_task(self._run_loop(monitor))
        self._tasks[monitor.id] = task

    async def _run_loop(self, monitor: Monitor) -> None:
        while self._running:
            try:
                await self._run_check(monitor)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor {} check error: {}", monitor.id, e)

            await asyncio.sleep(monitor.interval_seconds)

            if not self._running:
                break

            refreshed = self._store.load_monitor(monitor.id)
            if refreshed and refreshed.status != MonitorStatus.ACTIVE:
                break

    async def _run_check(self, monitor: Monitor) -> None:
        start = time.time()
        handler = self._handlers.get(monitor.type.value)
        if not handler:
            logger.warning("No handler for monitor type: {}", monitor.type.value)
            return

        check = MonitorCheck(
            monitor_id=monitor.id,
            checked_at=time.time(),
        )

        try:
            result = await handler(monitor)
            elapsed = (time.time() - start) * 1000
            check.response_time_ms = elapsed
            check.result = result
            check.status = "up"

            check.triggered = self._evaluator.check_all(monitor.conditions, result)

            if check.triggered:
                alert_msg = self._build_alert_message(monitor, check)
                await self._alerts.dispatch(monitor, check, alert_msg)

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            check.response_time_ms = elapsed
            check.status = "down"
            check.error = str(e)
            check.result = {"error": str(e)}

            has_down_condition = any(
                c.metric == "status" and c.operator == ConditionOperator.EQ and c.value == "down"
                for c in monitor.conditions
            )
            check.triggered = has_down_condition or not monitor.conditions

            if check.triggered:
                alert_msg = self._build_alert_message(monitor, check)
                await self._alerts.dispatch(monitor, check, alert_msg)

        monitor.last_check = check
        self._store.save_check(check)

    def _build_alert_message(self, monitor: Monitor, check: MonitorCheck) -> str:
        status_icon = "✅" if check.status == "up" else "❌"
        lines = [
            f"{status_icon} Monitor: {monitor.name}",
            f"   Type: {monitor.type.value}",
            f"   Target: {monitor.target}",
            f"   Status: {check.status}",
        ]
        if check.response_time_ms is not None:
            lines.append(f"   Response: {check.response_time_ms:.0f}ms")
        if check.error:
            lines.append(f"   Error: {check.error}")
        if check.result:
            for k, v in list(check.result.items())[:5]:
                lines.append(f"   {k}: {v}")
        return "\n".join(lines)

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from raven.core.monitor.checkers.http_check import check_http
from raven.core.monitor.checkers.price import check_price
from raven.core.monitor.checkers.rss import check_rss
from raven.core.monitor.models import CheckResult, Monitor, MonitorCheck, MonitorStatus, MonitorType
from raven.core.monitor.store import MonitorStore


class MonitorEngine:
    def __init__(
        self,
        store_or_path: MonitorStore | str | Path,
        send_fn: Callable[[str, str], Any] | None = None,
    ):
        if isinstance(store_or_path, MonitorStore):
            self._store = store_or_path
        else:
            self._store = MonitorStore(str(store_or_path))
        self._send_fn = send_fn
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._handlers: dict[str, Callable] = {}

    @classmethod
    def from_db(cls, db_path: str, send_fn: Callable | None = None) -> MonitorEngine:
        return cls(db_path, send_fn=send_fn)

    def bind_send(self, send_fn: Callable[[str, str], Any]):
        self._send_fn = send_fn

    def register_handler(self, monitor_type: str, handler: Callable):
        self._handlers[monitor_type] = handler

    async def start(self):
        self._running = True
        monitors = self._store.list_active()
        for m in monitors:
            self._schedule_monitor(m)
        logger.info("MonitorEngine started with {} monitors", len(monitors))

    async def stop(self):
        self._running = False
        for mid, task in list(self._tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("MonitorEngine stopped")

    def pause_monitor(self, monitor_id: str) -> bool:
        m = self._store.load_monitor(monitor_id)
        if not m:
            return False
        self._store.update_status(monitor_id, MonitorStatus.PAUSED)
        task = self._tasks.pop(monitor_id, None)
        if task:
            task.cancel()
        return True

    def resume_monitor(self, monitor_id: str) -> bool:
        m = self._store.load_monitor(monitor_id)
        if not m:
            return False
        self._store.update_status(monitor_id, MonitorStatus.ACTIVE)
        if self._running:
            self._schedule_monitor(m)
        return True

    def list_monitors(self, user_id: str | None = None) -> list[Monitor]:
        return self._store.list_monitors(user_id=user_id)

    def add_monitor(self, monitor: Monitor):
        self._store.save_monitor(monitor)
        if monitor.status == MonitorStatus.ACTIVE and self._running:
            self._schedule_monitor(monitor)

    def remove_monitor(self, monitor_id: str):
        task = self._tasks.pop(monitor_id, None)
        if task:
            task.cancel()
        self._store.delete_monitor(monitor_id)

    async def check_now(self, monitor_id: str) -> str | None:
        monitor = self._store.load_monitor(monitor_id)
        if not monitor:
            return None
        alert_text = await self._run_check(monitor)
        if alert_text:
            await self._alert(monitor, alert_text)
        return alert_text

    def _schedule_monitor(self, monitor: Monitor):
        if monitor.id in self._tasks:
            self._tasks[monitor.id].cancel()
        self._tasks[monitor.id] = asyncio.create_task(self._run_loop(monitor))

    async def _run_loop(self, monitor: Monitor):
        while self._running:
            try:
                alert_text = await self._run_check(monitor)
                if alert_text and self._running:
                    await self._alert(monitor, alert_text)
                await asyncio.sleep(monitor.interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor {} loop error: {}", monitor.id, e)
                await asyncio.sleep(60)

    async def _run_check(self, monitor: Monitor) -> str | None:
        start = time.time()
        try:
            handler = self._handlers.get(monitor.type.value)
            if handler:
                alert_text = await handler(monitor)
            elif monitor.type == MonitorType.HTTP:
                alert_text = await check_http(monitor)
            elif monitor.type == MonitorType.PRICE:
                alert_text = await check_price(monitor)
            elif monitor.type == MonitorType.RSS:
                alert_text = await check_rss(monitor)
            elif monitor.type == MonitorType.FILE:
                alert_text = await self._check_file(monitor)
            elif monitor.type == MonitorType.PROCESS:
                alert_text = await self._check_process(monitor)
            else:
                return None

            triggered = alert_text is not None
            status = "up" if not triggered else "down"
            elapsed = (time.time() - start) * 1000

            check = MonitorCheck(
                monitor_id=monitor.id,
                status=status,
                result={"alert": alert_text} if alert_text else {},
                error=None,
                triggered=triggered,
                checked_at=time.time(),
                response_time_ms=elapsed,
            )
            monitor.last_check = CheckResult(
                status=status,
                checked_at=check.checked_at,
                response_time_ms=elapsed,
                triggered=triggered,
                error=None,
            )
            self._store.save_check(check)

            return alert_text

        except Exception as e:
            logger.error("Monitor {} check failed: {}", monitor.id, e)
            check = MonitorCheck(
                monitor_id=monitor.id,
                status="error",
                result={"error": str(e)},
                error=str(e),
                triggered=False,
                checked_at=time.time(),
                response_time_ms=(time.time() - start) * 1000,
            )
            monitor.last_check = CheckResult(
                status="error",
                checked_at=check.checked_at,
                response_time_ms=check.response_time_ms,
                triggered=False,
                error=str(e),
            )
            self._store.save_check(check)
            return None

    async def _check_file(self, monitor: Monitor) -> str | None:
        from pathlib import Path

        path = Path(monitor.config.get("target", monitor.target))
        if not path.exists():
            return f"🔴 File not found: {path}"
        return None

    async def _check_process(self, monitor: Monitor) -> str | None:
        import subprocess
        import sys

        name = monitor.config.get("target", monitor.target)
        if sys.platform == "win32":
            cmd = f'tasklist /FI "IMAGENAME eq {name}" 2>NUL'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            running = name.lower() in result.stdout.lower()
        else:
            result = subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=10)
            running = result.returncode == 0
        if not running:
            return f"🔴 Process not running: {name}"
        return None

    async def _alert(self, monitor: Monitor, alert_text: str):
        if not monitor.should_notify():
            logger.debug("Monitor {} cooldown active, skipping alert", monitor.id)
            return
        channel_id = monitor.channel or monitor.config.get("channel")
        if self._send_fn and channel_id:
            await self._send_fn(channel_id, alert_text)
        logger.info("Monitor {} alert: {}", monitor.id, alert_text[:100])

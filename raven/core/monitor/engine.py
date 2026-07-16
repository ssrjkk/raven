from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.monitor.checkers.http_check import check_http
from raven.core.monitor.checkers.price import check_price
from raven.core.monitor.checkers.rss import check_rss
from raven.core.monitor.models import CheckResult, Monitor, MonitorCheck, MonitorStatus, MonitorType
from raven.core.monitor.store import MonitorStore
from raven.core.periodic_engine import PeriodicEngine


class MonitorEngine(PeriodicEngine[Monitor, MonitorStatus, MonitorStore]):
    def __init__(
        self,
        store_or_path: MonitorStore | str | Path,
        send_fn: Any = None,
    ):
        if isinstance(store_or_path, MonitorStore):
            store = store_or_path
        else:
            store = MonitorStore(str(store_or_path))
        super().__init__(store, send_fn=send_fn)

    @classmethod
    def from_db(cls, db_path: str, send_fn: Any = None) -> MonitorEngine:
        return cls(db_path, send_fn=send_fn)

    async def list_monitors(self, user_id: str | None = None, limit: int = 50, offset: int = 0) -> list[Monitor]:
        return await self._store.list_monitors(user_id=user_id, limit=limit, offset=offset)

    async def count_monitors(self, user_id: str | None = None) -> int:
        return await self._store.count_monitors(user_id=user_id)

    async def add_monitor(self, monitor: Monitor):
        await self.add_item(monitor)

    async def remove_monitor(self, monitor_id: str):
        await self.remove_item(monitor_id)

    async def pause_monitor(self, monitor_id: str) -> bool:
        return await self.pause_item(monitor_id)

    async def resume_monitor(self, monitor_id: str) -> bool:
        return await self.resume_item(monitor_id)

    async def check_now(self, monitor_id: str) -> str | None:
        monitor = await self._load_item(monitor_id)
        if not monitor:
            return None
        alert_text = await self._run_item(monitor)
        if alert_text:
            await self._alert(monitor, alert_text)
        return alert_text

    async def _run_loop(self, monitor: Monitor):
        while self._running:
            try:
                alert_text = await self._run_item(monitor)
                if alert_text and self._running:
                    await self._alert(monitor, alert_text)
                await asyncio.sleep(monitor.interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor {} loop error: {}", monitor.id, e)
                await asyncio.sleep(60)

    async def _run_item(self, monitor: Monitor) -> str | None:
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
                checked_at=check.checked_at or time.time(),
                response_time_ms=elapsed,
                triggered=triggered,
                error=None,
            )
            await self._store.save_check(check)

            return alert_text  # type: ignore[no-any-return]

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
                checked_at=check.checked_at or time.time(),
                response_time_ms=check.response_time_ms,
                triggered=False,
                error=str(e),
            )
            await self._store.save_check(check)
            return None

    async def _list_active(self) -> list[Monitor]:
        return await self._store.list_active()

    async def _load_item(self, item_id: str) -> Monitor | None:
        return await self._store.load_monitor(item_id)

    async def _save_item(self, item: Monitor):
        await self._store.save_monitor(item)

    async def _delete_item(self, item_id: str):
        await self._store.delete_monitor(item_id)

    async def _update_status(self, item_id: str, status: MonitorStatus):
        await self._store.update_status(item_id, status)

    def _get_item_id(self, item: Monitor) -> str:
        return item.id

    def _is_active(self, item: Monitor) -> bool:
        return item.status == MonitorStatus.ACTIVE

    def _get_interval(self, item: Monitor) -> int | float:
        return item.interval_seconds

    def _paused_status(self) -> MonitorStatus:
        return MonitorStatus.PAUSED

    def _active_status(self) -> MonitorStatus:
        return MonitorStatus.ACTIVE

    async def _check_file(self, monitor: Monitor) -> str | None:
        from pathlib import Path

        path = Path(monitor.config.get("target", monitor.target))
        if not path.exists():
            return f"🔴 File not found: {path}"
        return None

    async def _check_process(self, monitor: Monitor) -> str | None:
        import sys

        name = monitor.config.get("target", monitor.target)
        if not name:
            return "No process name configured"
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                "tasklist",
                "/FI",
                f"IMAGENAME eq {name}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            running = name.lower() in stdout.decode("utf-8", errors="replace").lower()
        else:
            proc = await asyncio.create_subprocess_exec(
                "pgrep",
                "-f",
                name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            running = proc.returncode == 0
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

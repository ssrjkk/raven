from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.events import EventBus
from raven.core.monitor.checkers.http_check import check_http
from raven.core.monitor.checkers.price import check_price
from raven.core.monitor.checkers.rss import check_rss
from raven.core.monitor.models import (
    CheckResult,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    MonitorType,
    SLOStats,
)
from raven.core.monitor.store import MonitorStore
from raven.core.periodic_engine import PeriodicEngine

_ADAPTIVE_THRESHOLD = 3
_ADAPTIVE_CAP_SECONDS = 3600


class MonitorEngine(PeriodicEngine[Monitor, MonitorStatus, MonitorStore]):
    def __init__(
        self,
        store_or_path: MonitorStore | str | Path,
        send_fn: Any = None,
        event_bus: EventBus | None = None,
    ):
        if isinstance(store_or_path, MonitorStore):
            store = store_or_path
        else:
            store = MonitorStore(str(store_or_path))
        super().__init__(store, send_fn=send_fn)
        self._event_bus = event_bus
        self._consecutive_failures: dict[str, int] = {}
        self._consecutive_successes: dict[str, int] = {}
        self._effective_intervals: dict[str, int] = {}

    @classmethod
    def from_db(cls, db_path: str, send_fn: Any = None) -> MonitorEngine:
        return cls(db_path, send_fn=send_fn)

    async def list_monitors(self, user_id: str | None = None, limit: int = 50, offset: int = 0) -> list[Monitor]:
        return await self._store.list_monitors(user_id=user_id, limit=limit, offset=offset)

    async def count_monitors(self, user_id: str | None = None) -> int:
        return await self._store.count_monitors(user_id=user_id)

    async def add_monitor(self, monitor: Monitor) -> None:
        await self.add_item(monitor)

    async def remove_monitor(self, monitor_id: str) -> None:
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

    def effective_interval(self, monitor_id: str, base: int) -> int:
        return self._effective_intervals.get(monitor_id, base)

    def adaptive_state(self) -> dict[str, Any]:
        return {
            "intervals": dict(self._effective_intervals),
            "consecutive_failures": dict(self._consecutive_failures),
            "consecutive_successes": dict(self._consecutive_successes),
        }

    async def get_slo(self, monitor_id: str) -> SLOStats | None:
        monitor = await self._load_item(monitor_id)
        if not monitor:
            return None
        stats = await self._store.get_slo_stats(monitor.id, monitor.slo_window_seconds)
        return SLOStats(
            target=monitor.slo_target,
            window_seconds=monitor.slo_window_seconds,
            total_checks=stats["total"],
            ok_checks=stats["ok"],
            fail_checks=stats["fail"],
        )

    async def slo_report(self, limit: int = 1000, offset: int = 0) -> list[dict[str, Any]]:
        monitors = await self.list_monitors(limit=limit, offset=offset)
        report: list[dict[str, Any]] = []
        for m in monitors:
            stats = await self._store.get_slo_stats(m.id, m.slo_window_seconds)
            slo = SLOStats(
                target=m.slo_target,
                window_seconds=m.slo_window_seconds,
                total_checks=stats["total"],
                ok_checks=stats["ok"],
                fail_checks=stats["fail"],
            )
            report.append(
                {
                    "monitor_id": m.id,
                    "name": m.name,
                    "group": m.group,
                    "type": m.type.value,
                    "status": m.status.value,
                    "effective_interval": self.effective_interval(m.id, m.interval_seconds),
                    "slo_breached": stats["total"] > 0 and slo.error_budget_remaining <= 0,
                    **slo.to_dict(),
                }
            )
        return report

    async def _run_loop(self, monitor: Monitor) -> None:
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
            self._update_adaptive(monitor, triggered)

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
            self._update_adaptive(monitor, True)
            return None

    async def _list_active(self) -> list[Monitor]:
        return await self._store.list_active()

    async def _load_item(self, item_id: str) -> Monitor | None:
        return await self._store.load_monitor(item_id)

    async def _save_item(self, item: Monitor) -> None:
        await self._store.save_monitor(item)

    async def _delete_item(self, item_id: str) -> None:
        await self._store.delete_monitor(item_id)

    async def _update_status(self, item_id: str, status: MonitorStatus) -> None:
        await self._store.update_status(item_id, status)

    def _get_item_id(self, item: Monitor) -> str:
        return item.id

    def _is_active(self, item: Monitor) -> bool:
        return item.status == MonitorStatus.ACTIVE

    def _get_interval(self, item: Monitor) -> int | float:
        return self._effective_intervals.get(item.id, item.interval_seconds)

    def _update_adaptive(self, monitor: Monitor, triggered: bool) -> None:
        monitor_id = monitor.id
        base = monitor.interval_seconds
        if triggered:
            failures = self._consecutive_failures.get(monitor_id, 0) + 1
            self._consecutive_failures[monitor_id] = failures
            self._consecutive_successes[monitor_id] = 0
            if failures >= _ADAPTIVE_THRESHOLD:
                current = self._effective_intervals.get(monitor_id, base)
                new = min(current * 2, _ADAPTIVE_CAP_SECONDS)
                self._effective_intervals[monitor_id] = new
                self._consecutive_failures[monitor_id] = 0
                logger.info("Monitor {} adaptive: interval {}s -> {}s", monitor_id, current, new)
        else:
            successes = self._consecutive_successes.get(monitor_id, 0) + 1
            self._consecutive_successes[monitor_id] = successes
            self._consecutive_failures[monitor_id] = 0
            if successes >= _ADAPTIVE_THRESHOLD:
                self._effective_intervals[monitor_id] = base
                self._consecutive_successes[monitor_id] = 0
                logger.info("Monitor {} adaptive: interval restored to {}s", monitor_id, base)

    def _paused_status(self) -> MonitorStatus:
        return MonitorStatus.PAUSED

    def _active_status(self) -> MonitorStatus:
        return MonitorStatus.ACTIVE

    async def _check_file(self, monitor: Monitor) -> str | None:
        from pathlib import Path

        path = Path(monitor.config.get("target", monitor.target))
        exists = await asyncio.to_thread(path.exists)
        if not exists:
            return f"File not found: {path}"
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

    async def _alert(self, monitor: Monitor, alert_text: str) -> None:
        if not monitor.should_notify():
            logger.debug("Monitor {} cooldown active, skipping alert", monitor.id)
            return
        channel_id = monitor.channel or monitor.config.get("channel")
        if self._send_fn and channel_id:
            await self._send_fn(channel_id, alert_text)
        logger.info("Monitor {} alert: {}", monitor.id, alert_text[:100])
        if self._event_bus is not None:
            await self._event_bus.publish(
                "monitor.alert",
                monitor_id=monitor.id,
                status=monitor.status.value if monitor.status else "",
                channel=channel_id or "",
                text=alert_text[:200],
            )

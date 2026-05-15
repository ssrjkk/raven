from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.monitor.models import (
    CheckResult,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    MonitorType,
)
from raven.core.monitor.store import MonitorStore


class MonitorEngine:
    def __init__(self, store: MonitorStore):
        self._store = store
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._handlers: dict[str, Callable] = {}
        self._gateway_ref: Any = None

    def bind_gateway(self, gateway: Any):
        self._gateway_ref = gateway

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

    def _schedule_monitor(self, monitor: Monitor):
        if monitor.id in self._tasks:
            self._tasks[monitor.id].cancel()
        self._tasks[monitor.id] = asyncio.create_task(
            self._run_loop(monitor)
        )

    async def _run_loop(self, monitor: Monitor):
        while self._running:
            try:
                await self._check(monitor)
                await asyncio.sleep(monitor.interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor {} check error: {}", monitor.id, e)
                await asyncio.sleep(60)

    async def _check(self, monitor: Monitor):
        start = time.time()
        try:
            handler = self._handlers.get(monitor.type.value)
            if handler:
                result_data = await handler(monitor)
            elif monitor.type == MonitorType.HTTP:
                result_data = await self._check_http(monitor)
            elif monitor.type == MonitorType.PRICE:
                result_data = await self._check_price(monitor)
            elif monitor.type == MonitorType.RSS:
                result_data = await self._check_rss(monitor)
            elif monitor.type == MonitorType.FILE:
                result_data = self._check_file(monitor)
            elif monitor.type == MonitorType.PROCESS:
                result_data = self._check_process(monitor)
            else:
                return

            if result_data is None:
                result_data = {}

            status_code = result_data.get("status_code", 200) if isinstance(result_data, dict) else 200
            status = "up" if status_code < 400 and result_data.get("error") is None else "down"
            error = result_data.get("error") if isinstance(result_data, dict) else None

            check = MonitorCheck(
                monitor_id=monitor.id,
                status=status,
                result=result_data if isinstance(result_data, dict) else {},
                error=error,
                triggered=status == "down" or bool(error),
                checked_at=time.time(),
                response_time_ms=(time.time() - start) * 1000,
            )
            monitor.last_check = CheckResult(
                status=check.status,
                checked_at=check.checked_at,
                response_time_ms=check.response_time_ms,
                triggered=check.triggered,
                error=check.error,
            )
            self._store.save_check(check)

            audit_logger.log(
                AuditEventType.MESSAGE_RECEIVED,
                "monitor",
                monitor.id,
                detail={"type": monitor.type.value, "target": monitor.target, "status": check.status, "triggered": check.triggered},
            )

            if check.triggered:
                await self._alert(monitor, check)

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

    async def _check_http(self, monitor: Monitor) -> dict[str, Any]:
        url = monitor.config.get("target", monitor.target)
        method = monitor.config.get("method", "GET")
        headers = monitor.config.get("headers", {})
        timeout = monitor.config.get("timeout", 15)

        from raven.core.http_client import HTTPClientPool
        client = await HTTPClientPool.get_instance().get_client(timeout=timeout)
        if method.upper() == "GET":
            resp = await client.get(url, headers=headers)
        else:
            resp = await client.post(url, json=monitor.config.get("body"), headers=headers)
        return {"status_code": resp.status_code, "response_time_ms": resp.elapsed.total_seconds() * 1000 if hasattr(resp, "elapsed") else None}

    async def _check_price(self, monitor: Monitor) -> dict[str, Any]:
        symbol = monitor.config.get("target", monitor.target)
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        from raven.core.http_client import client_manager
        data = await client_manager.get(url)
        return {"price": data.get("price"), "status_code": 200}

    async def _check_rss(self, monitor: Monitor) -> dict[str, Any]:
        from raven.core.monitor.checkers.rss import check_rss_feed
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, check_rss_feed, monitor, self._store)
        return result

    def _check_file(self, monitor: Monitor) -> dict[str, Any]:
        path = monitor.config.get("target", monitor.target)
        import os
        exists = os.path.exists(path)
        return {"exists": exists, "status_code": 200 if exists else 404}

    def _check_process(self, monitor: Monitor) -> dict[str, Any]:
        name = monitor.config.get("target", monitor.target)
        import subprocess
        import sys
        if sys.platform == "win32":
            cmd = f'tasklist /FI "IMAGENAME eq {name}" 2>NUL'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            running = name.lower() in result.stdout.lower()
        else:
            result = subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=10)
            running = result.returncode == 0
        return {"running": running, "status_code": 200 if running else 404}

    async def _alert(self, monitor: Monitor, check: MonitorCheck):
        from raven.core.monitor.alert import AlertDispatcher
        d = AlertDispatcher()
        if self._gateway_ref:
            d.bind_gateway(self._gateway_ref)
        msg = d.format_alert(monitor, check)
        await d.dispatch(monitor, check, msg)

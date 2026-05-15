from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.http_client import client_manager
from raven.core.monitor.models import (
    CheckResult,
    Monitor,
    MonitorStatus,
    MonitorType,
)
from raven.core.monitor.store import MonitorStore


class MonitorEngine:
    def __init__(self, store: MonitorStore):
        self._store = store
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._gateway_ref: Any = None

    def bind_gateway(self, gateway: Any):
        self._gateway_ref = gateway

    async def start(self):
        self._running = True
        monitors = self._store.list_active_monitors()
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

    def pause_monitor(self, monitor_id: str):
        self._store.update_status(monitor_id, MonitorStatus.PAUSED)
        task = self._tasks.pop(monitor_id, None)
        if task:
            task.cancel()

    def resume_monitor(self, monitor_id: str):
        self._store.update_status(monitor_id, MonitorStatus.ACTIVE)
        m = self._store.load_monitor(monitor_id)
        if m:
            self._schedule_monitor(m)

    def list_monitors(self) -> list[Monitor]:
        return self._store.list_monitors()

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
            if monitor.type == MonitorType.HTTP:
                result = await self._check_http(monitor)
            elif monitor.type == MonitorType.PRICE:
                result = await self._check_price(monitor)
            elif monitor.type == MonitorType.RSS:
                result = await self._check_rss(monitor)
            elif monitor.type == MonitorType.FILE:
                result = self._check_file(monitor)
            elif monitor.type == MonitorType.PROCESS:
                result = self._check_process(monitor)
            else:
                return

            result.response_time_ms = (time.time() - start) * 1000
            result.triggered = self._evaluate_conditions(monitor, result)
            monitor.last_check = result
            self._store.save_check(monitor.id, result)

            audit_logger.log(
                AuditEventType.MESSAGE_RECEIVED,
                "monitor",
                monitor.id,
                detail={"type": monitor.type.value, "target": monitor.target, "status": result.status, "triggered": result.triggered},
            )

            if result.triggered:
                await self._alert(monitor, result)

        except Exception as e:
            logger.error("Monitor {} check failed: {}", monitor.id, e)
            result = CheckResult(
                status="error",
                checked_at=time.time(),
                response_time_ms=(time.time() - start) * 1000,
                triggered=False,
                error=str(e),
            )
            monitor.last_check = result
            self._store.save_check(monitor.id, result)

    async def _check_http(self, monitor: Monitor) -> CheckResult:
        url = monitor.config.get("target", monitor.target)
        method = monitor.config.get("method", "GET")
        headers = monitor.config.get("headers", {})
        timeout = monitor.config.get("timeout", 15)

        try:
            from raven.core.http_client import HTTPClientPool
            client = await HTTPClientPool.get_instance().get_client(timeout=timeout)
            if method.upper() == "GET":
                resp = await client.get(url, headers=headers)
            else:
                resp = await client.post(url, json=monitor.config.get("body"), headers=headers)
            status_code = resp.status_code
            return CheckResult(
                status="up" if status_code < 400 else "down",
                checked_at=time.time(),
                triggered=status_code >= 400,
                response_time_ms=resp.elapsed.total_seconds() * 1000 if hasattr(resp, "elapsed") else None,
            )
        except Exception as e:
            return CheckResult(
                status="down",
                checked_at=time.time(),
                triggered=True,
                error=str(e),
            )

    async def _check_price(self, monitor: Monitor) -> CheckResult:
        symbol = monitor.config.get("target", monitor.target)
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
            await client_manager.get(url)
            return CheckResult(
                status="up",
                checked_at=time.time(),
                triggered=False,
            )
        except Exception as e:
            return CheckResult(
                status="error",
                checked_at=time.time(),
                triggered=False,
                error=str(e),
            )

    async def _check_rss(self, monitor: Monitor) -> CheckResult:
        from raven.core.monitor.checkers.rss import check_rss_feed
        return await asyncio.get_event_loop().run_in_executor(
            None, check_rss_feed, monitor, self._store
        )

    def _check_file(self, monitor: Monitor) -> CheckResult:
        path = monitor.config.get("target", monitor.target)
        import os
        try:
            exists = os.path.exists(path)
            return CheckResult(
                status="up" if exists else "down",
                checked_at=time.time(),
                triggered=not exists,
            )
        except Exception as e:
            return CheckResult(
                status="error",
                checked_at=time.time(),
                triggered=False,
                error=str(e),
            )

    def _check_process(self, monitor: Monitor) -> CheckResult:
        name = monitor.config.get("target", monitor.target)
        import subprocess
        import sys
        try:
            if sys.platform == "win32":
                cmd = f'tasklist /FI "IMAGENAME eq {name}" 2>NUL'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                running = name.lower() in result.stdout.lower()
            else:
                result = subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=10)
                running = result.returncode == 0
            return CheckResult(
                status="up" if running else "down",
                checked_at=time.time(),
                triggered=not running,
            )
        except Exception as e:
            return CheckResult(
                status="error",
                checked_at=time.time(),
                triggered=False,
                error=str(e),
            )

    def _evaluate_conditions(self, monitor: Monitor, result: CheckResult) -> bool:
        if not monitor.conditions:
            return result.status == "down"
        for cond in monitor.conditions:
            if cond.metric == "status":
                if cond.evaluate(result.status):
                    return True
            elif cond.metric == "response_time_ms" and result.response_time_ms is not None:
                if cond.evaluate(result.response_time_ms):
                    return True
        return False

    async def _alert(self, monitor: Monitor, result: CheckResult):
        if not monitor.should_notify():
            return
        channels = monitor.notify_channels or [monitor.channel] if monitor.channel else []
        msg = self._format_alert(monitor, result)
        for ch in channels:
            await self._send_alert(ch, monitor.user_id, msg)

    def _format_alert(self, monitor: Monitor, result: CheckResult) -> str:
        return (
            f" Monitor Alert: {monitor.name}\n"
            f"Type: {monitor.type.value}\n"
            f"Target: {monitor.target}\n"
            f"Status: {result.status}\n"
            f"{'Error: ' + result.error if result.error else ''}"
        )

    async def _send_alert(self, channel: str, user_id: str, text: str):
        if not self._gateway_ref:
            return
        session_id = f"{channel}:{user_id}:monitor"
        await self._gateway_ref._send(channel, session_id, text)

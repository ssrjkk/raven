from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.monitor.models import Monitor, MonitorCheck


class AlertDispatcher:
    """Group-aware alert dispatcher: N consecutive failures in a (group, code) fire once, then reset."""

    def __init__(self, min_consecutive: int = 3) -> None:
        self._gateway_ref: Any = None
        self._min_consecutive = max(1, min_consecutive)
        self._streaks: dict[tuple[str, str], int] = {}

    def reset(self) -> None:
        self._streaks.clear()

    def streak(self, monitor: Monitor, check: MonitorCheck) -> int:
        return self._streaks.get((monitor.group or "default", check.status or "unknown"), 0)

    async def dispatch(self, monitor: Monitor, check: MonitorCheck, message: str) -> None:
        group = monitor.group or "default"
        key = (group, check.status or "unknown")
        if check.status == "up":
            for stale in [k for k in self._streaks if k[0] == group]:
                self._streaks.pop(stale, None)
            return
        count = self._streaks.get(key, 0) + 1
        self._streaks[key] = count
        if count < self._min_consecutive:
            logger.debug(
                "Alert suppressed (streak {}/{} for {}): {}", count, self._min_consecutive, key, monitor.name
            )
            return
        self._streaks[key] = 0
        logger.info("Alert fired: {} — {} ({} consecutive)", monitor.name, message, count)
        await audit_logger.log(
            AuditEventType.MESSAGE_RECEIVED,
            "alert",
            monitor.id,
            detail={"message": message, "status": check.status, "group": monitor.group, "streak": count},
        )
        if self._gateway_ref:
            session_id = f"{monitor.channel}:{monitor.user_id}:monitor"
            await self._gateway_ref._send(monitor.channel or "telegram", session_id, message)

    def format_alert(self, monitor: Monitor, check: MonitorCheck) -> str:
        return (
            f" Monitor Alert: {monitor.name}\n"
            f"Type: {monitor.type.value}\n"
            f"Target: {monitor.target}\n"
            f"Status: {check.status}\n"
            f"{'Error: ' + check.error if check.error else ''}"
        )

from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.monitor.models import Monitor, MonitorCheck


class AlertDispatcher:
    def __init__(self):
        self._gateway_ref: Any = None

    async def dispatch(self, monitor: Monitor, check: MonitorCheck, message: str):
        logger.info("Alert: {} — {}", monitor.name, message)
        audit_logger.log(
            AuditEventType.MESSAGE_RECEIVED,
            "alert",
            monitor.id,
            detail={"message": message, "status": check.status},
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

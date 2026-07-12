from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from loguru import logger

try:
    from raven.automation.channel_router import ChannelRouter, ChannelType, NormalizedMessage
    from raven.channels.base import BaseChannel  # noqa: F401
    _CHANNELS_AVAILABLE = True
except ImportError:
    _CHANNELS_AVAILABLE = False


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ApprovalRequest:
    id: str
    action: str
    context: dict[str, Any] = field(default_factory=dict)
    channel: str = "web"
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = 0.0
    responded_at: float = 0.0
    timeout: float = 3600.0
    auto_approve_on_timeout: bool = False
    response: str = ""
    responded_by: str = ""


@dataclass
class ApprovalAuditEntry:
    request_id: str
    action: str
    status: ApprovalStatus
    timestamp: float
    channel: str
    responded_by: str = ""
    response: str = ""


@dataclass
class InteractivePrompt:
    id: str
    request_id: str
    channel: str
    message: str
    options: dict[str, Any] = field(default_factory=dict)
    timeout: float = 3600.0


class HumanApproval:
    def __init__(self, default_timeout: float = 3600.0) -> None:
        self._default_timeout = default_timeout
        self._pending: dict[str, ApprovalRequest] = {}
        self._audit: list[ApprovalAuditEntry] = []
        self._handlers: dict[str, Callable[..., Awaitable[None]]] = {}
        self._response_events: dict[str, asyncio.Event] = {}

    def register_channel_handler(self, channel: str, handler: Callable[..., Awaitable[None]]) -> None:
        self._handlers[channel] = handler

    async def request_approval(
        self,
        action: str,
        context: dict[str, Any] | None = None,
        channel: str = "web",
        timeout: float | None = None,
        auto_approve: bool = False,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:12],
            action=action,
            context=context or {},
            channel=channel,
            created_at=time.time(),
            timeout=timeout or self._default_timeout,
            auto_approve_on_timeout=auto_approve,
        )
        self._pending[req.id] = req
        self._response_events[req.id] = asyncio.Event()

        handler = self._handlers.get(channel)
        if handler:
            try:
                await handler(request_id=req.id, action=action, context=req.context, channel=channel)
            except Exception as exc:
                logger.warning("[human_approval] handler error for {}: {}", req.id, exc)

        try:
            await asyncio.wait_for(self._response_events[req.id].wait(), timeout=req.timeout)
        except TimeoutError:
            if req.auto_approve_on_timeout:
                await self._resolve(req.id, ApprovalStatus.APPROVED, "system", "Auto-approved (timeout)")
            else:
                await self._resolve(req.id, ApprovalStatus.TIMEOUT, "system", "Timeout")

        self._response_events.pop(req.id, None)
        return self._pending.pop(req.id, req)

    async def respond(self, request_id: str, approved: bool, responded_by: str = "", response: str = "") -> bool:
        req = self._pending.get(request_id)
        if not req:
            logger.warning("[human_approval] unknown request: {}", request_id)
            return False
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        await self._resolve(request_id, status, responded_by, response)
        return True

    async def cancel(self, request_id: str) -> bool:
        req = self._pending.get(request_id)
        if not req:
            return False
        await self._resolve(request_id, ApprovalStatus.CANCELLED, "system", "Cancelled")
        self._pending.pop(request_id, None)
        return True

    async def _resolve(self, request_id: str, status: ApprovalStatus, responded_by: str, response: str) -> None:
        req = self._pending.get(request_id)
        if not req:
            return
        req.status = status
        req.responded_at = time.time()
        req.response = response
        req.responded_by = responded_by

        self._audit.append(ApprovalAuditEntry(
            request_id=request_id, action=req.action,
            status=status, timestamp=req.responded_at,
            channel=req.channel, responded_by=responded_by, response=response,
        ))

        event = self._response_events.get(request_id)
        if event:
            event.set()

    def get_pending(self) -> list[ApprovalRequest]:
        return list(self._pending.values())

    def get_audit(self, limit: int = 50) -> list[ApprovalAuditEntry]:
        return self._audit[-limit:]

    def get_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {"total": len(self._audit), "pending": len(self._pending)}
        for entry in self._audit:
            key = entry.status.value
            stats[key] = stats.get(key, 0) + 1
        return stats

    async def request_approval_via_channel(
        self,
        action: str,
        channel_type: str,
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
        auto_approve: bool = False,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:12],
            action=action,
            context=context or {},
            channel=channel_type,
            created_at=time.time(),
            timeout=timeout or self._default_timeout,
            auto_approve_on_timeout=auto_approve,
        )
        self._pending[req.id] = req
        self._response_events[req.id] = asyncio.Event()

        InteractivePrompt(
            id=uuid.uuid4().hex[:12],
            request_id=req.id,
            channel=channel_type,
            message=action,
            options={"auto_approve": auto_approve},
            timeout=req.timeout,
        )

        if _CHANNELS_AVAILABLE:
            try:
                router = ChannelRouter()
                ct = ChannelType(channel_type)
                msg = NormalizedMessage(
                    text=f"Approval required: {action}\nContext: {req.context}",
                    source_channel=ct,
                    user_id="system",
                )
                await router.send_message(ct, msg)
                logger.info("[human_approval] sent prompt via channel '{}' for request {}", channel_type, req.id)
            except Exception as exc:
                logger.warning("[human_approval] failed to send via channel '{}': {}", channel_type, exc)

        try:
            await asyncio.wait_for(self._response_events[req.id].wait(), timeout=req.timeout)
        except TimeoutError:
            if req.auto_approve_on_timeout:
                await self._resolve(req.id, ApprovalStatus.APPROVED, "system", "Auto-approved (timeout)")
            else:
                await self._resolve(req.id, ApprovalStatus.TIMEOUT, "system", "Timeout")

        self._response_events.pop(req.id, None)
        return self._pending.pop(req.id, req)

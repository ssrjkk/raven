from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.channels.enterprise_base import EnterpriseChannel, RateLimiter
from raven.core.audit import AuditEventType
from raven.core.models import IncomingMessage, Message


class _ConcreteChannel(EnterpriseChannel):
    channel_id = "concrete"

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False
        self.sent: list[str] = []
        self.send_error: Exception | None = None

    async def _start(self) -> None:
        self.started = True

    async def _stop(self) -> None:
        self.stopped = True

    async def _send_message(self, session_id: str, message: Message) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(message.content)


def _msg(content: str = "hello") -> Message:
    return Message(session_id="concrete:chan:u1", channel="concrete", role="assistant", content=content)


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limiter_decrements_when_tokens_available() -> None:
    limiter = RateLimiter(max_per_minute=30)
    before = limiter._tokens
    await limiter.acquire()
    assert limiter._tokens < before


@pytest.mark.asyncio
async def test_rate_limiter_sleeps_when_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("raven.channels.enterprise_base.asyncio.sleep", sleep)
    limiter = RateLimiter(max_per_minute=30)
    limiter._tokens = 0.0
    await limiter.acquire()
    sleep.assert_awaited()
    assert limiter._tokens == 0


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_sets_ready_and_stop_clears() -> None:
    c = _ConcreteChannel()
    await c.start()
    assert c._ready and c.started
    assert await c.health_check() is True
    await c.stop()
    assert not c._ready and c.stopped


@pytest.mark.asyncio
async def test_stop_is_noop_when_not_ready() -> None:
    c = _ConcreteChannel()
    await c.stop()  # never started
    assert c.stopped is False


@pytest.mark.asyncio
async def test_connect_disconnect_delegate_to_start_stop() -> None:
    c = _ConcreteChannel()
    await c.connect()
    assert c._ready
    await c.disconnect()
    assert not c._ready


@pytest.mark.asyncio
async def test_on_message_stores_handler() -> None:
    c = _ConcreteChannel()
    handler = AsyncMock()
    await c.on_message(handler)
    assert c._handler is not None
    msg = IncomingMessage(channel="concrete", user_id="u", session_id="s", text="t")
    await c._handler(msg)
    handler.assert_awaited_once_with(msg)


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_skips_when_not_ready() -> None:
    c = _ConcreteChannel()
    await c.send("concrete:chan:u1", _msg())
    assert c.sent == []
    assert c._stats["sent"] == 0


@pytest.mark.asyncio
async def test_send_increments_sent() -> None:
    c = _ConcreteChannel()
    await c.start()
    await c.send("concrete:chan:u1", _msg("body"))
    assert c.sent == ["body"]
    assert c._stats["sent"] == 1


@pytest.mark.asyncio
async def test_send_increments_failed_on_error() -> None:
    c = _ConcreteChannel()
    c.send_error = RuntimeError("down")
    await c.start()
    await c.send("concrete:chan:u1", _msg())
    assert c._stats["failed"] == 1
    assert c._stats["sent"] == 0


def test_stats_includes_channel() -> None:
    c = _ConcreteChannel()
    s = c.stats()
    assert s["channel"] == "concrete"
    assert {"sent", "failed", "received", "reconnects"} <= set(s)


# ---------------------------------------------------------------------------
# _post
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_delegates_to_client_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    post = AsyncMock(return_value={"ok": 1})
    monkeypatch.setattr("raven.channels.enterprise_base.client_manager.post", post)
    c = _ConcreteChannel()
    result = await c._post("https://x/y", {"a": 1}, headers={"H": "v"}, timeout=5)
    assert result == {"ok": 1}
    post.assert_awaited_once_with("https://x/y", json={"a": 1}, headers={"H": "v"}, timeout=5)


@pytest.mark.asyncio
async def test_post_defaults_headers_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    post = AsyncMock(return_value={})
    monkeypatch.setattr("raven.channels.enterprise_base.client_manager.post", post)
    c = _ConcreteChannel()
    await c._post("https://x/y", {"a": 1})
    assert post.await_args_list[0].kwargs["headers"] == {}


# ---------------------------------------------------------------------------
# _retry_call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_succeeds_first_attempt() -> None:
    fn = AsyncMock(return_value="ok")
    c = _ConcreteChannel()
    assert await c._retry_call(fn) == "ok"
    assert fn.await_count == 1


@pytest.mark.asyncio
async def test_retry_backs_off_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("raven.channels.enterprise_base.asyncio.sleep", sleep)
    fn = AsyncMock(side_effect=[ValueError("1"), ValueError("2"), "ok"])
    c = _ConcreteChannel()
    assert await c._retry_call(fn, max_retries=3, base_delay=1.0) == "ok"
    assert fn.await_count == 3
    # exponential waits: 1s then 2s
    assert [call.args[0] for call in sleep.await_args_list] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_retry_raises_last_error_when_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("raven.channels.enterprise_base.asyncio.sleep", sleep)
    fn = AsyncMock(side_effect=ValueError("always"))
    c = _ConcreteChannel()
    with pytest.raises(ValueError, match="always"):
        await c._retry_call(fn, max_retries=2)
    assert fn.await_count == 2


@pytest.mark.asyncio
async def test_retry_zero_attempts_hits_unreachable() -> None:
    fn = AsyncMock()
    c = _ConcreteChannel()
    with pytest.raises(RuntimeError, match="Unreachable"):
        await c._retry_call(fn, max_retries=0)
    fn.assert_not_awaited()


# ---------------------------------------------------------------------------
# audit helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_send_parses_user_from_session(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = MagicMock()
    audit.log = AsyncMock()
    metrics = MagicMock()
    monkeypatch.setattr("raven.channels.enterprise_base.audit_logger", audit)
    monkeypatch.setattr("raven.channels.enterprise_base.metrics", metrics)
    c = _ConcreteChannel()
    await c._audit_send("concrete:chan:u42", _msg("abcd"))
    event = audit.log.await_args.args[0]
    assert audit.log.await_args.args[1] == "channel:concrete"
    assert audit.log.await_args.args[2] == "chan"
    assert audit.log.await_args.kwargs["detail"] == {"length": 4}
    metrics.inc.assert_called_once()
    assert event is AuditEventType.MESSAGE_SENT


@pytest.mark.asyncio
async def test_audit_send_without_colon_uses_whole_session(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = MagicMock()
    audit.log = AsyncMock()
    monkeypatch.setattr("raven.channels.enterprise_base.audit_logger", audit)
    monkeypatch.setattr("raven.channels.enterprise_base.metrics", MagicMock())
    c = _ConcreteChannel()
    await c._audit_send("nosep", _msg("x"))
    assert audit.log.await_args.args[2] == "nosep"


@pytest.mark.asyncio
async def test_audit_receive_logs_and_increments(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = MagicMock()
    audit.log = AsyncMock()
    metrics = MagicMock()
    monkeypatch.setattr("raven.channels.enterprise_base.audit_logger", audit)
    monkeypatch.setattr("raven.channels.enterprise_base.metrics", metrics)
    c = _ConcreteChannel()
    await c._audit_receive("u9", "hello")
    assert audit.log.await_args.args[1] == "u9"
    assert audit.log.await_args.kwargs["detail"] == {"length": 5}
    metrics.inc.assert_called_once()

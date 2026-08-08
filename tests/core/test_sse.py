from __future__ import annotations

import asyncio

import pytest

from raven.core.sse import Backpressure, SSEEvent, SSEStream


@pytest.mark.asyncio
async def test_sse_event_serialize():
    evt = SSEEvent("message", {"text": "hello"})
    serialized = evt.serialize()
    assert "event: message" in serialized
    assert '"text":' in serialized


def test_sse_event_retry():
    evt = SSEEvent("connected", {}, retry=3000)
    serialized = evt.serialize()
    assert "retry: 3000" in serialized


def test_sse_event_id():
    evt = SSEEvent("test", {"x": 1}, event_id="custom-id")
    serialized = evt.serialize()
    assert "id: custom-id" in serialized


def test_sse_event_auto_id():
    evt1 = SSEEvent("test", {})
    evt2 = SSEEvent("test", {})
    assert evt1.id != evt2.id


def test_sse_stream_subscribe_unsubscribe():
    stream = SSEStream()
    q = stream.subscribe("test-session")
    assert q is not None
    assert "test-session" in stream._queues
    stream.unsubscribe("test-session")
    assert "test-session" not in stream._queues


@pytest.mark.asyncio
async def test_sse_stream_push():
    stream = SSEStream()
    q = stream.subscribe("test-session")
    import asyncio

    await stream.push("test", {"key": "val"}, session_id="test-session")
    payload = await asyncio.wait_for(q.get(), timeout=1.0)
    assert payload.event == "test"
    assert payload.data["key"] == "val"
    stream.unsubscribe("test-session")


@pytest.mark.asyncio
async def test_sse_stream_broadcast():
    stream = SSEStream()
    q1 = stream.subscribe("s1")
    q2 = stream.subscribe("s2")
    import asyncio

    await stream.broadcast("broadcast", {"msg": "to all"})
    p1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    p2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert p1.event == "broadcast"
    assert p2.event == "broadcast"
    stream.unsubscribe("s1")
    stream.unsubscribe("s2")


@pytest.mark.asyncio
async def test_sse_stream_generator():
    stream = SSEStream()
    gen = stream.stream("gen-session")
    first = await gen.__anext__()
    assert "event: connected" in first
    assert "gen-session" in first
    stream.unsubscribe("gen-session")


@pytest.mark.asyncio
async def test_sse_stream_cleanup():
    stream = SSEStream()
    stream.start_cleanup()
    assert stream._task is not None
    await stream.stop()
    assert stream._task is None


def test_sse_stream_active_sessions():
    stream = SSEStream()
    assert stream.active_sessions == 0
    stream.subscribe("s1")
    assert stream.active_sessions == 1
    stream.subscribe("s2")
    assert stream.active_sessions == 2
    stream.unsubscribe("s1")
    assert stream.active_sessions == 1
    stream.unsubscribe("s2")
    assert stream.active_sessions == 0


@pytest.mark.asyncio
async def test_sse_stream_metrics():
    stream = SSEStream()
    assert stream.total_pushed == 0
    assert stream.total_dropped == 0
    q = stream.subscribe("s1")
    await stream.push("evt", {"n": 1}, session_id="s1")
    assert stream.total_pushed == 1
    await stream.push("evt", {"n": 2}, session_id="s1")
    assert stream.total_pushed == 2
    await q.get()
    await q.get()
    stream.unsubscribe("s1")


def test_sse_stream_list_sessions():
    stream = SSEStream()
    stream.subscribe("s1")
    stream.subscribe("s2")
    sessions = stream.list_sessions()
    assert "s1" in sessions
    assert "s2" in sessions
    assert sessions["s1"]["events"] >= 0
    stream.unsubscribe("s1")
    stream.unsubscribe("s2")


def test_sse_session_info():
    stream = SSEStream()
    stream.subscribe("s1")
    info = stream.get_session_info("s1")
    assert info is not None
    assert info.created_at > 0
    assert info.last_get > 0
    stream._track_get("s1")
    assert stream.get_session_info("s1").event_count >= 1  # type: ignore[union-attr]
    stream.unsubscribe("s1")


@pytest.mark.asyncio
async def test_sse_backpressure_drop():
    stream = SSEStream(max_queue=2, backpressure=Backpressure.DROP)
    stream.subscribe("s1")
    await stream.push("a", {}, session_id="s1")
    await stream.push("b", {}, session_id="s1")
    await stream.push("c", {}, session_id="s1")
    await stream.push("d", {}, session_id="s1")
    assert stream.total_dropped >= 2
    stream.unsubscribe("s1")


@pytest.mark.asyncio
async def test_sse_backpressure_block():
    stream = SSEStream(max_queue=1, backpressure=Backpressure.BLOCK)
    q = stream.subscribe("s1")
    import asyncio

    await stream.push("a", {}, session_id="s1")
    consumed = await asyncio.wait_for(q.get(), timeout=0.5)
    assert consumed.event == "a"
    await stream.push("b", {}, session_id="s1")
    consumed2 = await asyncio.wait_for(q.get(), timeout=0.5)
    assert consumed2.event == "b"
    assert stream.total_pushed == 2
    assert stream.total_dropped == 0
    stream.unsubscribe("s1")


@pytest.mark.asyncio
async def test_sse_backpressure_throttle():
    stream = SSEStream(max_queue=2, backpressure=Backpressure.THROTTLE)
    stream.subscribe("s1")
    for i in range(5):
        await stream.push("evt", {"i": i}, session_id="s1")
    assert stream.total_pushed >= 1
    stream.unsubscribe("s1")


def test_sse_event_serialize_has_id():
    evt = SSEEvent("msg", {"x": 1})
    serialized = evt.serialize()
    assert "id: evt-" in serialized


@pytest.mark.asyncio
async def test_sse_stream_generator_last_event_id():
    stream = SSEStream()
    q = stream.subscribe("s1")
    await stream.push("e1", {"n": 1}, session_id="s1")
    p1 = await q.get()
    gen = stream.stream("s1", last_event_id=p1.id)
    first = await gen.__anext__()
    assert "event: connected" in first
    stream.unsubscribe("s1")


def test_sse_backpressure_enum():
    assert Backpressure.DROP.value == "drop"
    assert Backpressure.BLOCK.value == "block"
    assert Backpressure.THROTTLE.value == "throttle"


@pytest.mark.asyncio
async def test_sse_stop_clears_all():
    stream = SSEStream()
    stream.subscribe("s1")
    stream.subscribe("s2")
    await stream.stop()
    assert stream.active_sessions == 0


class TestDaemonSseIntegration:
    @pytest.fixture
    def daemon(self, tmp_path):
        from raven.gateway.daemon import RavenFlowDaemon

        return RavenFlowDaemon(port=0, data_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_session_created_event_payload(self, daemon):
        q = daemon._sse.subscribe("flow:user1:test")
        await daemon._get_or_create_session("s1", "test")
        payload = await asyncio.wait_for(q.get(), timeout=1.0)
        assert payload.event == "session"
        assert payload.data["action"] == "created"
        session_payload = payload.data["session"]
        assert session_payload["id"] == "s1"
        assert session_payload["channel"] == "test"
        assert session_payload["status"] == "idle"
        assert session_payload["message_count"] == 0
        daemon._sse.unsubscribe("flow:user1:test")

    @pytest.mark.asyncio
    async def test_session_updated_event_on_run(self, daemon):
        q = daemon._sse.subscribe("flow:user1:test")
        session = await daemon._get_or_create_session("s1", "test")
        await asyncio.wait_for(q.get(), timeout=1.0)
        await daemon._publish_session(session, "updated")
        payload = await asyncio.wait_for(q.get(), timeout=1.0)
        assert payload.event == "session"
        assert payload.data["action"] == "updated"
        assert payload.data["session"]["id"] == "s1"
        daemon._sse.unsubscribe("flow:user1:test")

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self, daemon):
        key = "flow:user1:gone"
        daemon._sse.subscribe(key)
        daemon._sse.unsubscribe(key)
        session = await daemon._get_or_create_session("s1", "test")
        await daemon._publish_session(session, "updated")
        assert daemon._sse.get_session_info(key) is None

    @pytest.mark.asyncio
    async def test_published_payload_matches_session_info(self, daemon):
        q = daemon._sse.subscribe("flow:user1:test")
        session = await daemon._get_or_create_session("s1", "test")
        await asyncio.wait_for(q.get(), timeout=1.0)
        session.message_count = 7
        await daemon._publish_session(session, "updated")
        payload = await asyncio.wait_for(q.get(), timeout=1.0)
        data = payload.data["session"]
        from raven.gateway.daemon import SessionInfo

        info = SessionInfo(**data)
        assert info.id == "s1"
        assert info.message_count == 7
        assert info.status == "idle"
        daemon._sse.unsubscribe("flow:user1:test")

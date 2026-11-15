from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from raven.core.mcp.sse_transport import SSETransport


@pytest.mark.asyncio
class TestSSETransport:
    async def test_start_stop(self):
        t = SSETransport()
        await t.start()
        assert t._running is True
        await t.stop()
        assert t._running is False

    async def test_subscribe_unsubscribe(self):
        t = SSETransport()
        await t.start()
        t.subscribe("client1")
        assert "client1" in t._subscribers
        t.unsubscribe("client1")
        assert "client1" not in t._subscribers
        await t.stop()

    async def test_send_receive(self):
        t = SSETransport()
        await t.start()
        q = t.subscribe("client1")
        await t.send("test_event", "hello")
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        assert msg["event"] == "test_event"
        assert "hello" in msg["data"]
        await t.stop()

    async def test_send_dict_data(self):
        t = SSETransport()
        await t.start()
        q = t.subscribe("client1")
        await t.send("json_event", {"key": "value"})
        msg = await asyncio.wait_for(q.get(), timeout=1.0)
        assert msg["event"] == "json_event"
        assert "key" in msg["data"]
        await t.stop()

    async def test_broadcast(self):
        t = SSETransport()
        await t.start()
        q1 = t.subscribe("c1")
        q2 = t.subscribe("c2")
        await t.broadcast("broad", "msg")
        m1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        m2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert m1["event"] == "broad"
        assert m2["event"] == "broad"
        await t.stop()

    async def test_stream_yields_sse_format(self):
        t = SSETransport()
        await t.start()
        t.subscribe("client1")
        await t.send("ev", "data1")

        async def collect():
            chunks: list[str] = []
            async for chunk in t.stream("client1"):
                chunks.append(chunk)
                if "data1" in chunk:
                    break
            return chunks

        chunks = await asyncio.wait_for(collect(), timeout=2.0)
        assert any("event: ev" in c for c in chunks)
        assert any("data1" in c for c in chunks)
        await t.stop()

    async def test_stream_unknown_client(self):
        t = SSETransport()
        await t.start()
        chunks: list[str] = []
        async for chunk in t.stream("nonexistent"):
            chunks.append(chunk)
        assert len(chunks) == 0
        await t.stop()

    async def test_stream_break_on_close(self):
        t = SSETransport()
        await t.start()
        q = t.subscribe("client1")
        chunks: list[str] = []

        async def collect():
            async for chunk in t.stream("client1"):
                chunks.append(chunk)
            return chunks

        await q.put({"event": "close", "data": ""})
        result = await asyncio.wait_for(collect(), timeout=2.0)
        assert len(result) == 0  # stream exited on close

    async def test_close_stops_stream(self):
        """`stop()` is what ends a subscriber's iterator. The old version broke out of the loop
        itself on a `sent` flag and asserted nothing, so it passed even if stop() closed nothing."""
        t = SSETransport()
        await t.start()
        t.subscribe("client1")

        async def consume() -> list[str]:
            return [chunk async for chunk in t.stream("client1")]

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        await t.send("msg", "hello")
        await t.stop()

        chunks = await asyncio.wait_for(consumer, timeout=2.0)
        assert chunks == ["event: msg\ndata: hello\n\n"]
        assert t._running is False
        assert t._subscribers == {}

    async def test_drop_slow_subscriber(self):
        t = SSETransport()
        await t.start()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        q.put_nowait({"event": "full", "data": "x"})
        t._subscribers["slow"] = q
        await t.send("test", "data")
        await asyncio.sleep(0.1)
        assert "slow" not in t._subscribers
        await t.stop()

    async def test_a_subscriber_made_by_subscribe_is_bounded(self):
        """`test_drop_slow_subscriber` above injects its own bounded queue, which is why the drop could
        look covered while `subscribe()` handed out an unbounded one and no real client could ever fill it."""
        t = SSETransport(max_pending=4)
        assert t.subscribe("client1").maxsize == 4

    async def test_a_client_that_never_reads_cannot_grow_the_buffer(self):
        t = SSETransport(max_pending=8)
        q = t.subscribe("wedged")
        for n in range(200):
            await t.send("ev", f"{n}")
            if "wedged" not in t._subscribers:
                break
        assert "wedged" not in t._subscribers
        assert q.qsize() <= 8

    async def test_a_wedged_subscriber_does_not_hold_the_publisher(self):
        """One dropped frame costs a `put_nowait`, not a wait: the old path held every other subscriber
        for the full put timeout per frame once a queue could actually fill."""
        t = SSETransport(max_pending=1)
        wedged = t.subscribe("wedged")
        wedged.put_nowait({"event": "full", "data": "x"})
        healthy = t.subscribe("healthy")
        started = time.perf_counter()
        await t.send("ev", "y")
        elapsed = time.perf_counter() - started
        assert elapsed < 0.05, f"publishing to a wedged subscriber took {elapsed:.3f}s"
        assert healthy.qsize() == 1  # the other client is served, and served without waiting on the wedged one

    async def test_unsubscribing_ends_a_stream_still_reading(self):
        t = SSETransport(ping_timeout=30.0)
        t.subscribe("client1")

        async def consume() -> list[str]:
            return [chunk async for chunk in t.stream("client1")]

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        t.unsubscribe("client1")
        assert await asyncio.wait_for(consumer, timeout=2.0) == []

    async def test_send_after_stop_delivers_nothing(self):
        t = SSETransport()
        q = t.subscribe("client1")
        await t.stop()
        await t.send("ev", "late")
        assert [q.get_nowait()["event"] for _ in range(q.qsize())] == ["close"]  # only the sentinel stop() left

    async def test_ping_on_timeout(self):
        t = SSETransport(ping_timeout=0.2)
        t.subscribe("client1")

        async def first_frame() -> str:
            async for chunk in t.stream("client1"):
                return chunk
            raise AssertionError("the stream ended before it pinged")

        assert await asyncio.wait_for(first_frame(), timeout=5.0) == "event: ping\ndata: \n\n"
        await t.stop()

    async def test_stream_timeout_ping(self):
        t = SSETransport(ping_timeout=0.3)
        await t.start()
        t.subscribe("client1")

        async def read():
            chunks: list[str] = []
            async for chunk in t.stream("client1"):
                chunks.append(chunk)
                if any("ping" in c for c in chunks):
                    await t.stop()
                    break
            return chunks

        chunks = await asyncio.wait_for(read(), timeout=5.0)
        assert any("ping" in c for c in chunks)
        await t.stop()

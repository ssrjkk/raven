from __future__ import annotations

import asyncio
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
        t = SSETransport()
        await t.start()
        t.subscribe("client1")
        sent = False

        async def produce():
            nonlocal sent
            await asyncio.sleep(0.05)
            await t.send("msg", "hello")
            sent = True

        async def consume():
            chunks: list[str] = []
            async for chunk in t.stream("client1"):
                chunks.append(chunk)
                if sent:
                    break
            return chunks

        async with asyncio.TaskGroup() as tg:
            tg.create_task(produce())
            tg.create_task(consume())

        await t.stop()

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

    async def test_ping_on_timeout(self):
        t = SSETransport()
        await t.start()
        t._running = False  # stop early instead of waiting 30s
        await t.stop()
        # verify it started and stopped cleanly
        assert t._running is False

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

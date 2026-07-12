from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from raven.automation.channel_router import ChannelRouter, ChannelType
from raven.core.context_router import ContextRouter
from raven.core.shared_memory import SharedMemory
from raven.core.tool_registry import ToolRegistry
from raven.unique.collaboration import RealTimeCollaboration, TextChange


def _measure_p95(timings: list[float]) -> float:
    sorted_t = sorted(timings)
    idx = int(len(sorted_t) * 0.95)
    return sorted_t[idx]


class TestMetricsLatency:
    def setup_method(self) -> None:
        self.router = ContextRouter()
        self.memory = SharedMemory()
        self.tool_registry = ToolRegistry()
        self.channel_router = ChannelRouter()

    def test_context_router_classify_latency(self):
        self.router.classify("write a function to calculate fibonacci")
        timings: list[float] = []
        for _ in range(100):
            start = time.perf_counter()
            self.router.classify("write a function to calculate fibonacci")
            timings.append(time.perf_counter() - start)
        p95 = _measure_p95(timings)
        assert p95 < 0.1

    def test_shared_memory_store_latency(self):
        self.memory.store("warmup", "value")
        timings: list[float] = []
        for i in range(100):
            start = time.perf_counter()
            self.memory.store(f"key{i}", "x" * 100)
            timings.append(time.perf_counter() - start)
        p95 = _measure_p95(timings)
        assert p95 < 0.1

    def test_tool_registry_register_latency(self):
        async def dummy(**kwargs: object) -> str:
            return "ok"

        self.tool_registry.register("coding", "warmup", dummy)
        timings: list[float] = []
        for i in range(100):
            start = time.perf_counter()
            self.tool_registry.register("coding", f"tool_{i}", dummy)
            timings.append(time.perf_counter() - start)
        p95 = _measure_p95(timings)
        assert p95 < 0.1

    @pytest.mark.asyncio
    async def test_collaboration_edit_latency(self):
        collab = RealTimeCollaboration()
        await collab.create_session("latency-test", "test.py")
        await collab.join_session("latency-test", "user1", "Alice")
        changes = [
            TextChange(
                user_id="user1",
                file="test.py",
                start_line=0,
                start_col=0,
                end_line=0,
                end_col=0,
                old_text="",
                new_text="hello world",
            )
        ]
        await collab.edit("user1", changes)
        timings: list[float] = []
        for _ in range(100):
            change = TextChange(
                user_id="user1",
                file="test.py",
                start_line=0,
                start_col=0,
                end_line=0,
                end_col=11,
                old_text="hello world",
                new_text="hello world!",
            )
            start = time.perf_counter()
            await collab.apply_change("latency-test", change)
            timings.append(time.perf_counter() - start)
        p95 = _measure_p95(timings)
        assert p95 < 0.1

    def test_channel_router_normalize_latency(self):
        self.channel_router.normalize_message("hello", ChannelType.TELEGRAM, {"user_id": "u1"})
        timings: list[float] = []
        for _ in range(100):
            start = time.perf_counter()
            self.channel_router.normalize_message(
                "hello world this is a test message",
                ChannelType.TELEGRAM,
                {"user_id": "u1", "user_name": "Alice"},
            )
            timings.append(time.perf_counter() - start)
        p95 = _measure_p95(timings)
        assert p95 < 0.1

    @pytest.mark.asyncio
    async def test_unified_agent_dispatch_latency(self):
        from raven.core.unified_agent import UnifiedAgent

        agent = UnifiedAgent()
        agent.handle_coding = AsyncMock(return_value="ok")  # type: ignore[method-assign]
        agent.handle_automation = AsyncMock(return_value="ok")
        agent.handle_hybrid = AsyncMock(return_value="ok")
        agent.handle_query = AsyncMock(return_value="ok")

        await agent.process("write a function")

        timings: list[float] = []
        for _ in range(100):
            start = time.perf_counter()
            await agent.process("write a function")
            timings.append(time.perf_counter() - start)
        p95 = _measure_p95(timings)
        assert p95 < 0.1

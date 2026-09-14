from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from ravencode.runtime.agent_core import (
    AgentConfig,
    EventEmitter,
    ReActAgent,
    _AdaptiveRateLimiter,
)
from ravencode.runtime.context import Conversation


def _patch_save(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class TestAdaptiveRateLimiter:
    async def test_no_penalty_returns_immediately(self):
        limiter = _AdaptiveRateLimiter(clock=FakeClock())
        await asyncio.wait_for(limiter.acquire(), timeout=1)

    async def test_penalty_blocks_until_window_passes(self):
        clock = FakeClock()
        limiter = _AdaptiveRateLimiter(clock=clock)
        await limiter.penalize(2.0)
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)
            clock.t += seconds

        original_sleep = asyncio.sleep

        async def patched_sleep(seconds: float) -> None:
            if seconds == 0.25:
                await fake_sleep(seconds)
            else:
                await original_sleep(seconds)

        monkey = pytest.MonkeyPatch()
        try:
            monkey.setattr(asyncio, "sleep", patched_sleep)
            await asyncio.wait_for(limiter.acquire(), timeout=2)
        finally:
            monkey.undo()
        assert slept, "limiter must wait out the penalty window"
        assert clock.t >= 102.0

    async def test_repeated_penalties_escalate_and_cap(self):
        clock = FakeClock()
        limiter = _AdaptiveRateLimiter(clock=clock, max_penalty=10.0)
        await limiter.penalize(2.0)
        assert limiter.penalty == 2.0
        await limiter.penalize(2.0)
        assert limiter.penalty == 4.0
        await limiter.penalize(2.0)
        assert limiter.penalty == 8.0
        await limiter.penalize(2.0)
        assert limiter.penalty == 10.0
        await limiter.penalize(30.0)
        assert limiter.penalty == 10.0

    async def test_reset_clears_penalty(self):
        limiter = _AdaptiveRateLimiter(clock=FakeClock())
        await limiter.penalize(5.0)
        await limiter.reset()
        assert limiter.penalty == 0.0
        await asyncio.wait_for(limiter.acquire(), timeout=1)


class _FakeProvider:
    def __init__(self, script: Any) -> None:
        self.script = script  # list of either "raise" tuples or event lists
        self.calls = 0

    async def complete_stream_deltas(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        for ev in item:
            yield ev


def _rate_limit_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.example.com/chat")
    response = httpx.Response(429, headers={"retry-after": "1"}, request=request)
    return httpx.HTTPStatusError("rate limited", request=request, response=response)


@pytest.fixture
def router() -> Any:
    from raven.core.llm.router import LLMRouter

    return LLMRouter()


class TestRouterStreamDeltas:
    async def test_happy_path_passthrough(self, router: Any):
        events = [
            {"type": "token", "text": "he"},
            {"type": "token", "text": "y"},
            {"type": "tool_call", "index": 0, "id": "c1", "name": "read", "args_fragment": "{}"},
        ]
        monkey = pytest.MonkeyPatch()
        try:
            monkey.setattr(router, "_get_provider", lambda model: _FakeProvider([events]))
            got = [ev async for ev in router._stream_model_deltas([{"role": "user", "content": "x"}], "m", None)]
        finally:
            monkey.undo()
        assert got == events

    async def test_429_then_success(self, router: Any, monkeypatch: pytest.MonkeyPatch):
        events = [{"type": "token", "text": "ok"}]
        provider = _FakeProvider([_rate_limit_error(), events])
        monkeypatch.setattr(router, "_get_provider", lambda model: provider)
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        monkeypatch.setattr("raven.core.llm.router.asyncio.sleep", fake_sleep)
        got = [ev async for ev in router._stream_model_deltas([{"role": "user", "content": "x"}], "m", None)]
        assert got == events
        assert provider.calls == 2
        assert sleeps == [1]

    async def test_all_failures_fall_back_to_complete(self, router: Any, monkeypatch: pytest.MonkeyPatch):
        from raven.core.llm.protocol import LLMResponse

        provider = _FakeProvider([_rate_limit_error()])
        monkeypatch.setattr(router, "_get_provider", lambda model: provider)

        async def fake_sleep(seconds: float) -> None:
            pass

        monkeypatch.setattr("raven.core.llm.router.asyncio.sleep", fake_sleep)

        async def fake_complete(messages: Any, model: Any, tools: Any, key: Any) -> LLMResponse:
            return LLMResponse(content="final answer")

        monkeypatch.setattr(router, "_complete_with_failover", fake_complete)
        got = [ev async for ev in router._stream_model_deltas([{"role": "user", "content": "x"}], "m", None)]
        assert got == [{"type": "token", "text": "final answer"}]

    async def test_all_failures_with_tool_calls_fallback(self, router: Any, monkeypatch: pytest.MonkeyPatch):
        from raven.core.llm.protocol import LLMResponse, ToolCall

        provider = _FakeProvider([RuntimeError("down")])
        monkeypatch.setattr(router, "_get_provider", lambda model: provider)

        async def fake_sleep(seconds: float) -> None:
            pass

        monkeypatch.setattr("raven.core.llm.router.asyncio.sleep", fake_sleep)

        async def fake_complete(messages: Any, model: Any, tools: Any, key: Any) -> LLMResponse:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c1", name="write", arguments={"path": "a.txt"})],
            )

        monkeypatch.setattr(router, "_complete_with_failover", fake_complete)
        got = [ev async for ev in router._stream_model_deltas([{"role": "user", "content": "x"}], "m", None)]
        assert len(got) == 1
        ev = got[0]
        assert ev["type"] == "tool_call"
        assert (ev["index"], ev["id"], ev["name"]) == (0, "c1", "write")
        assert json.loads(ev["args_fragment"]) == {"path": "a.txt"}


class TestAIOSClientMessageStream:
    @staticmethod
    def _client_with(provider: Any) -> Any:
        from ravencode.api.client import AIOSClient

        client = AIOSClient()
        monkey = pytest.MonkeyPatch()

        def fake_require_llm() -> Any:
            return provider

        monkey.setattr(client, "_require_llm", fake_require_llm)
        monkeysetattr = monkey
        return client, monkeysetattr

    async def test_tokens_and_final_event(self):
        provider = _FakeProvider(
            [[
                {"type": "token", "text": "he"},
                {"type": "token", "text": "y"},
            ]]
        )
        client, monkey = self._client_with(provider)
        try:
            got = [ev async for ev in client.ask_messages_stream([{"role": "user", "content": "x"}])]
        finally:
            monkey.undo()
        assert got[-1] == {"type": "final", "content": "hey", "tool_calls": []}
        assert [ev for ev in got if ev["type"] == "token"] == [
            {"type": "token", "text": "he"},
            {"type": "token", "text": "y"},
        ]

    async def test_tool_call_fragments_assembled(self):
        provider = _FakeProvider(
            [[
                {"type": "tool_call", "index": 0, "id": "c1", "name": "write", "args_fragment": '{"pa'},
                {"type": "tool_call", "index": 0, "args_fragment": 'th": "a.txt"}'},
                {"type": "tool_call", "index": 1, "name": "read", "args_fragment": "{}"},
            ]]
        )
        client, monkey = self._client_with(provider)
        try:
            got = [ev async for ev in client.ask_messages_stream([{"role": "user", "content": "x"}])]
        finally:
            monkey.undo()
        final = got[-1]
        assert final["type"] == "final"
        assert final["tool_calls"] == [
            {"id": "c1", "name": "write", "arguments": {"path": "a.txt"}},
            {"id": "call_1", "name": "read", "arguments": {}},
        ]

    async def test_invalid_json_args_kept_raw(self):
        provider = _FakeProvider(
            [[{"type": "tool_call", "index": 0, "id": "c1", "name": "write", "args_fragment": "{oops"}]]
        )
        client, monkey = self._client_with(provider)
        try:
            got = [ev async for ev in client.ask_messages_stream([{"role": "user", "content": "x"}])]
        finally:
            monkey.undo()
        assert got[-1]["tool_calls"] == [{"id": "c1", "name": "write", "arguments": {"_raw": "{oops"}}]


class TestAgentStreaming:
    @staticmethod
    def _stream_client(script: list[list[dict[str, Any]]]) -> Any:
        class _FakeStreamClient:
            calls = 0  # class-level: agent_core instantiates AIOSClient() per step

            def __init__(self) -> None:
                pass

            async def ask_messages_stream(
                self, messages: list[dict[str, Any]], tools: Any = None
            ) -> Any:
                item = script[min(_FakeStreamClient.calls, len(script) - 1)]
                _FakeStreamClient.calls += 1
                for ev in item:
                    yield ev

        _FakeStreamClient.calls = 0
        return _FakeStreamClient

    async def test_agent_emits_token_events(self, monkeypatch: pytest.MonkeyPatch):
        _patch_save(monkeypatch)
        monkeypatch.setattr(
            "ravencode.runtime.agent_core.AIOSClient",
            self._stream_client(
                [[
                    {"type": "token", "text": "he"},
                    {"type": "token", "text": "y"},
                    {"type": "final", "content": "hey", "tool_calls": []},
                ]]
            ),
        )
        tokens: list[str] = []
        emitter = EventEmitter()
        emitter.on("token", lambda ev: _collect(tokens, ev))
        agent = ReActAgent(
            config=AgentConfig(
                proactive_scan=False,
                diff_preview=False,
                confirm_dangerous=False,
                max_steps=3,
                stream_tokens=True,
                event_emitter=emitter,
            ),
        )
        result = await agent.run("t")
        assert result == "hey"
        assert tokens == ["he", "y"]

    async def test_agent_streaming_with_tool_call(self, monkeypatch: pytest.MonkeyPatch):
        _patch_save(monkeypatch)
        monkeypatch.setattr(
            "ravencode.runtime.agent_core.AIOSClient",
            self._stream_client(
                [
                    [
                        {"type": "final", "content": "", "tool_calls": [
                            {"id": "c1", "name": "read", "arguments": {"path": "a"}}
                        ]},
                    ],
                    [
                        {"type": "token", "text": "done"},
                        {"type": "final", "content": "done", "tool_calls": []},
                    ],
                ]
            ),
        )
        exec_calls: list[str] = []

        async def fake_execute(name: str, args: dict[str, Any]) -> str:
            exec_calls.append(name)
            return "file-body"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        agent = ReActAgent(
            config=AgentConfig(
                proactive_scan=False,
                diff_preview=False,
                confirm_dangerous=False,
                max_steps=5,
                stream_tokens=True,
            ),
        )
        result = await agent.run("t")
        assert result == "done"
        assert exec_calls == ["read"]
        tool_msgs = [m for m in agent.conversation.messages if m.get("role") == "tool"]
        assert tool_msgs[0]["content"] == "file-body"


async def _collect(tokens: list[str], ev: Any) -> None:
    tokens.append(ev.data["content"])

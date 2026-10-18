from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar

import httpx
import pytest

from ravencode.api import server as srv
from ravencode.runtime.agent_core import AgentEvent


class _FakeAgent:
    """ReActAgent stand-in that replays scripted events through the emitter."""

    script: ClassVar[list[dict[str, Any]]] = []
    result: ClassVar[str] = ""
    last_init: ClassVar[dict[str, Any]] = {}
    last_content: ClassVar[str] = ""

    def __init__(self, conversation: Any = None, event_emitter: Any = None, **kwargs: Any) -> None:
        self.conversation = conversation
        cfg = kwargs.get("config")
        self.emitter = event_emitter or getattr(cfg, "event_emitter", None)
        _FakeAgent.last_init = {
            "conversation": conversation,
            "event_emitter": self.emitter,
            **kwargs,
        }

    async def run(self, content: str) -> str:
        _FakeAgent.last_content = content
        for item in _FakeAgent.script:
            if self.emitter is not None:
                await self.emitter.emit(type("AgentEvent", (), dict(item))())
        return _FakeAgent.result


@pytest.fixture
def fake_agent(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAgent]:
    monkeypatch.setattr(srv, "ReActAgent", _FakeAgent)
    return _FakeAgent


def _parse_sse(body: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    chunks: list[dict[str, Any]] = []
    comments: list[str] = []
    done: list[str] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            payload = line[6:]
            if payload == "[DONE]":
                done.append(payload)
            else:
                chunks.append(json.loads(payload))
        elif line.startswith(": "):
            comments.append(line[2:])
    return chunks, comments, done


def _msg(role: str, content: str | None = None, **kw: Any) -> Any:
    return srv.ChatMessage(role=role, content=content, **kw)


class TestSplitConversationInput:
    def test_user_last_excluded_and_replayed(self):
        messages = [_msg("system", "sys"), _msg("user", "hi")]
        conv, content = srv._split_conversation_input(messages)
        assert content == "hi"
        assert [m["role"] for m in conv.messages] == ["system"]

    def test_tool_calls_preserved_in_history(self):
        messages = [
            _msg("user", "do it"),
            _msg("assistant", "", tool_calls=[{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]),
            _msg("tool", "file body", tool_call_id="c1"),
            _msg("user", "thanks"),
        ]
        conv, _ = srv._split_conversation_input(messages)
        roles = [m["role"] for m in conv.messages]
        assert roles == ["user", "assistant", "tool"]
        assert conv.messages[1]["tool_calls"][0]["id"] == "c1"
        assert conv.messages[2]["tool_call_id"] == "c1"

    def test_tool_last_keeps_full_history(self):
        messages = [
            _msg("user", "do it"),
            _msg("assistant", "", tool_calls=[{"id": "c1"}]),
            _msg("tool", "result", tool_call_id="c1"),
        ]
        conv, content = srv._split_conversation_input(messages)
        assert len(conv.messages) == 3
        assert content == "Continue."


@pytest.mark.asyncio
async def test_stream_realtime_tokens_and_tool_comments(fake_agent: type[_FakeAgent], monkeypatch: pytest.MonkeyPatch):
    async def _auto_save(self: Any, reason: str) -> None:  # pragma: no cover
        pass

    monkeypatch.setattr("ravencode.runtime.agent_core.ReActAgent._auto_save", _auto_save)
    fake_agent.script = [
        {"type": "token", "data": {"content": "He"}},
        {"type": "tool_call", "data": {"name": "read", "args": {"path": "a.py"}, "step": 1}},
        {"type": "token", "data": {"content": "llo"}},
    ]
    fake_agent.result = "Hello"

    transport = httpx.ASGITransport(app=srv.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "ravencode", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
    assert resp.status_code == 200
    chunks, comments, done = _parse_sse(resp.text)

    assert done == ["[DONE]"]
    deltas = [c["choices"][0]["delta"] for c in chunks]
    assert deltas[0] == {"role": "assistant"}
    contents = [d.get("content") for d in deltas[1:] if d.get("content")]
    assert contents == ["He", "llo"], "tokens must stream as they are emitted, not after completion"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert any('"event": "tool_call"' in c for c in comments), "tool activity must ride as SSE comments"
    # full streamed content equals the final result
    assert "".join(contents) == fake_agent.result


@pytest.mark.asyncio
async def test_stream_fallback_chunks_when_no_tokens(fake_agent: type[_FakeAgent]):
    fake_agent.script = []
    fake_agent.result = "x" * 250

    transport = httpx.ASGITransport(app=srv.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "ravencode", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
    chunks, _comments, done = _parse_sse(resp.text)
    assert done == ["[DONE]"]
    contents = "".join(
        c["choices"][0]["delta"].get("content", "")
        for c in chunks
        if c["choices"][0]["delta"].get("content")
    )
    assert contents == "x" * 250


@pytest.mark.asyncio
async def test_nonstream_no_user_duplication(fake_agent: type[_FakeAgent]):
    fake_agent.script = []
    fake_agent.result = "answer"

    transport = httpx.ASGITransport(app=srv.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "ravencode",
                "messages": [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "hi"},
                ],
                "stream": False,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == "answer"
    conv = fake_agent.last_init["conversation"]
    roles = [m["role"] for m in conv.messages]
    assert roles == ["system"], "the final user message must not be duplicated in context"
    assert fake_agent.last_content == "hi"


async def _post(payload: dict[str, Any]) -> httpx.Response:
    transport = httpx.ASGITransport(app=srv.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/v1/chat/completions", json={"model": "ravencode", "messages": [{"role": "user", "content": "hi"}], **payload}
        )


@pytest.mark.asyncio
class TestMaxTokensBudget:
    async def test_nonstream_trims_completion_and_reports_length(self, fake_agent: type[_FakeAgent]):
        fake_agent.script = []
        fake_agent.result = "z" * 400
        resp = await _post({"max_tokens": 10})
        body = resp.json()
        assert body["choices"][0]["message"]["content"] == "z" * 40
        assert body["choices"][0]["finish_reason"] == "length"
        assert body["usage"]["completion_tokens"] == srv._estimate_tokens("z" * 40)

    async def test_stream_caps_emitted_tokens(self, fake_agent: type[_FakeAgent]):
        fake_agent.script = [
            {"type": "token", "data": {"content": "AAAA"}},
            {"type": "token", "data": {"content": "BBBB"}},
            {"type": "token", "data": {"content": "CCCC"}},
        ]
        fake_agent.result = "AAAABBBBCCCC"
        resp = await _post({"stream": True, "max_tokens": 2})
        chunks, _comments, done = _parse_sse(resp.text)
        assert done == ["[DONE]"]
        assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "AAAABBBB"
        assert chunks[-1]["choices"][0]["finish_reason"] == "length"

    @pytest.mark.parametrize("payload", [{"max_tokens": 0}, {"max_tokens": 200_001}, {"temperature": 3.0}])
    async def test_out_of_range_generation_params_are_rejected(self, payload: dict[str, Any]):
        assert (await _post(payload)).status_code == 422


class _EndlessAgent:
    """Agent stand-in that keeps streaming tokens until it is cancelled."""

    chunk: ClassVar[str] = "AAAA"
    cancelled: ClassVar[list[str]] = []

    def __init__(self, conversation: Any = None, event_emitter: Any = None, **kwargs: Any) -> None:
        cfg = kwargs.get("config")
        self.emitter: Any = event_emitter or getattr(cfg, "event_emitter", None)

    async def run(self, content: str) -> str:
        try:
            while True:
                await self.emitter.emit(AgentEvent("token", {"content": _EndlessAgent.chunk}))
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            _EndlessAgent.cancelled.append("cancelled")
            raise
        return "never reached"


@pytest.mark.asyncio
class TestStreamCancellation:
    async def test_client_disconnect_cancels_the_agent_run(self, monkeypatch: pytest.MonkeyPatch):
        _EndlessAgent.chunk = "hi"
        _EndlessAgent.cancelled = []
        monkeypatch.setattr(srv, "ReActAgent", _EndlessAgent)
        agen = srv._run_agent_stream([_msg("user", "hi")], "ravencode", 4096)
        assert '"role": "assistant"' in await agen.__anext__()
        assert "hi" in await agen.__anext__()

        await agen.aclose()
        await asyncio.sleep(0.01)
        assert _EndlessAgent.cancelled == ["cancelled"]

    async def test_truncated_stream_stops_the_agent_instead_of_burning_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _EndlessAgent.chunk = "AAAA"
        _EndlessAgent.cancelled = []
        monkeypatch.setattr(srv, "ReActAgent", _EndlessAgent)
        resp = await _post({"stream": True, "max_tokens": 2})
        chunks, _comments, done = _parse_sse(resp.text)
        assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "AAAAAAAA"
        assert chunks[-1]["choices"][0]["finish_reason"] == "length"
        assert done == ["[DONE]"]
        await asyncio.sleep(0.02)
        assert _EndlessAgent.cancelled == ["cancelled"]

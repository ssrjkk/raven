from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from raven.core.llm.providers.base import (
    _openai_chunk_to_events,
    collect_stream_deltas,
)


def _chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    choice: dict[str, Any] = {"delta": delta}
    if finish:
        choice["finish_reason"] = finish
    return {"choices": [choice]}


class TestOpenaiChunkToEvents:
    def test_content_token(self):
        events = _openai_chunk_to_events(_chunk({"content": "hello"}))
        assert events == [{"type": "token", "text": "hello"}]

    def test_tool_call_with_payload(self):
        events = _openai_chunk_to_events(
            _chunk({"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read", "arguments": '{"pa'}}]})
        )
        assert events == [
            {
                "type": "tool_call",
                "index": 0,
                "id": "c1",
                "name": "read",
                "args_fragment": '{"pa',
            }
        ]

    def test_empty_index_tool_call_skipped(self):
        events = _openai_chunk_to_events(_chunk({"tool_calls": [{"index": 0}]}))
        assert events == []

    def test_empty_delta(self):
        assert _openai_chunk_to_events(_chunk({})) == []

    def test_malformed_choices(self):
        assert _openai_chunk_to_events({"choices": ["bad"]}) == []
        assert _openai_chunk_to_events({}) == []


class TestCollectStreamDeltas:
    async def test_content_only(self):
        async def events() -> AsyncIterator[dict[str, Any]]:
            for ev in ({"type": "token", "text": "he"}, {"type": "token", "text": "y"}):
                yield ev

        content, calls = await collect_stream_deltas(events())
        assert content == "hey"
        assert calls == []

    async def test_tool_call_fragments_assembled_in_order(self):
        async def events() -> AsyncIterator[dict[str, Any]]:
            yield {"type": "tool_call", "index": 0, "id": "c1", "name": "write", "args_fragment": '{"pa'}
            yield {"type": "token", "text": "writing..."}
            yield {"type": "tool_call", "index": 0, "args_fragment": 'th": "a.txt"}'}
            yield {"type": "tool_call", "index": 1, "id": "c2", "name": "read", "args_fragment": "{}"}

        content, calls = await collect_stream_deltas(events())
        assert content == "writing..."
        assert [tc.id for tc in calls] == ["c1", "c2"]
        assert [tc.name for tc in calls] == ["write", "read"]
        assert calls[0].arguments == {"path": "a.txt"}
        assert calls[1].arguments == {}

    async def test_missing_id_gets_synthetic(self):
        async def events() -> AsyncIterator[dict[str, Any]]:
            yield {"type": "tool_call", "index": 2, "name": "bash", "args_fragment": json.dumps({"cmd": "ls"})}

        _, calls = await collect_stream_deltas(events())
        assert calls[0].id == "call_2"
        assert calls[0].arguments == {"cmd": "ls"}

    async def test_invalid_json_args_kept_raw(self):
        async def events() -> AsyncIterator[dict[str, Any]]:
            yield {"type": "tool_call", "index": 0, "id": "c1", "name": "write", "args_fragment": "{not json"}

        _, calls = await collect_stream_deltas(events())
        assert calls[0].arguments == {"_raw": "{not json"}

    async def test_non_dict_events_ignored(self):
        async def events() -> AsyncIterator[dict[str, Any]]:
            yield "garbage"  # type: ignore[misc]
            yield {"type": "token", "text": "ok"}

        content, calls = await collect_stream_deltas(events())
        assert content == "ok"
        assert calls == []

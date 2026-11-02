from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.gateway.message_processor import MessageProcessor, _mask_tool_args, usage_line


class _Policy:
    pass


def _msg(content: str, role: str = "user") -> Any:
    return SimpleNamespace(role=role, content=content, created_at=None, metadata={})


def _event(**over: Any) -> Any:
    base = dict(channel="web", user_id="u1", session_id="sid", text="hi", priority=1)
    base.update(over)
    return SimpleNamespace(**base)


def _processor(
    *,
    channel_obj: Any = None,
    ctxmgr: Any = None,
    msgs: list[Any] | None = None,
    prefs: dict[str, str] | None = None,
) -> tuple[MessageProcessor, AsyncMock, MagicMock]:
    db = MagicMock()
    db.get_or_create_session = AsyncMock(return_value=SimpleNamespace(sandbox_policy=None))
    db.get_session_messages = AsyncMock(return_value=msgs if msgs is not None else [])
    db.replace_session_messages = AsyncMock()
    registry = MagicMock()
    channels = MagicMock()
    channels.get = AsyncMock(return_value=channel_obj)
    metrics = MagicMock()
    metrics.inc = MagicMock()
    metrics.observe = MagicMock()
    send = AsyncMock()
    get_pref = None
    if prefs is not None:

        async def _get_pref(channel: str, user_id: str, key: str, default: str = "") -> str:
            return prefs.get(key, default)

        get_pref = AsyncMock(side_effect=_get_pref)
    proc = MessageProcessor(db, registry, channels, ctxmgr, metrics, send, get_pref_fn=get_pref)
    return proc, send, metrics


def _gen(tokens: list[str], *, confirm: Any = None, raise_exc: Exception | None = None) -> Any:
    async def _factory(confirm_fn: Any = None, history: Any = None) -> AsyncIterator[str]:
        if confirm is not None and confirm_fn is not None:
            await confirm_fn(confirm[0], confirm[1])
        for t in tokens:
            yield t
        if raise_exc is not None:
            raise raise_exc

    return _factory


def _agent(factory: Any) -> MagicMock:
    agent = MagicMock()
    # the shape a finished Agent.run leaves behind, so the processor is read against real counters
    agent.usage_totals = {"prompt": 40, "completion": 12, "rounds": 2}
    agent.show_tool_progress = True
    agent.trace = False
    agent.think_level = "high"
    agent.run = MagicMock(
        side_effect=lambda text, confirm_fn=None, history=None: factory(confirm_fn=confirm_fn, history=history)
    )
    return agent


@pytest.fixture(autouse=True)
def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.message_processor.settings", SimpleNamespace(agent_token_timeout=5.0)
    )
    monkeypatch.setattr(
        "raven.core.gateway.message_processor.get_policy_for_channel", lambda ch: _Policy()
    )


# ── _mask_tool_args ───────────────────────────────────────────────


def test_mask_tool_args_masks_secret_keys() -> None:
    out = _mask_tool_args({"api_key": "super-secret", "query": "hello"})
    assert "super-secret" not in out
    assert "***" in out


def test_mask_tool_args_nested_and_list() -> None:
    out = _mask_tool_args({"outer": {"token": "abc", "keep": "val"}, "arr": [{"password": "p"}]})
    assert "abc" not in out
    assert "val" in out


def test_mask_tool_args_truncates_200() -> None:
    out = _mask_tool_args({"data": "x" * 500})
    assert len(out) <= 200


def test_mask_tool_args_non_string_values() -> None:
    out = _mask_tool_args({"count": 42, "flag": True, "nested": {"n": 1}})
    assert "42" in out
    assert "True" in out


async def test_process_confirm_fn_without_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, send, _m = _processor(channel_obj=None)
    captured: dict[str, Any] = {}

    async def _factory(confirm_fn: Any = None, history: Any = None) -> AsyncIterator[str]:
        captured["allowed"] = await confirm_fn("tool", {"x": 1})
        yield "done"

    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_factory))
    await proc.process(_event(), "sid")
    # nobody was there to ask, so the tool is denied — an unanswered approval is not consent
    assert captured["allowed"] is False
    assert send.await_args_list[-1].args[2] == "done"


# ── process: non-streaming ────────────────────────────────────────


async def test_process_non_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, send, metrics = _processor(msgs=[_msg("old")])
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_gen(["Hel", "lo"])))
    await proc.process(_event(), "sid")
    send.assert_awaited_once_with("web", "sid", "Hello", streaming=False)
    metrics.inc.assert_any_call("messages_sent", {"channel": "web"})
    metrics.observe.assert_any_call("response_length", 5, {"channel": "web"})


async def test_process_empty_response_no_send(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, send, metrics = _processor()
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_gen(["  "])))
    await proc.process(_event(), "sid")
    send.assert_not_awaited()
    metrics.inc.assert_not_called()


# ── process: streaming ────────────────────────────────────────────


async def test_process_streams_and_flushes(monkeypatch: pytest.MonkeyPatch) -> None:
    channel_obj = SimpleNamespace(send_stream=MagicMock(), ask_confirmation=AsyncMock(return_value=True))
    proc, send, _metrics = _processor(channel_obj=channel_obj)
    # tokens: "a\n" flushes on newline, trailing "tail" flushes in the final buffer dump
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_gen(["a\n", "tail"])))
    await proc.process(_event(), "sid")
    stream_calls = [c for c in send.await_args_list if c.kwargs.get("streaming") is True]
    assert stream_calls[0].args[2] == "a\n"
    # leftover "tail" buffer is flushed at the end
    assert any(c.args[2] == "tail" for c in stream_calls)


async def test_process_confirm_fn_uses_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    channel_obj = SimpleNamespace(send_stream=MagicMock(), ask_confirmation=AsyncMock(return_value=False))
    proc, _send, _m = _processor(channel_obj=channel_obj)
    factory = _gen(["ok"], confirm=("tool_x", {"api_key": "zzz"}))
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(factory))
    await proc.process(_event(), "sid")
    desc = channel_obj.ask_confirmation.await_args.args[1]
    assert "tool_x" in desc
    assert "zzz" not in desc


# ── process: timeout ──────────────────────────────────────────────


async def test_process_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.message_processor.settings", SimpleNamespace(agent_token_timeout=0.05)
    )

    async def _slow(confirm_fn: Any = None, history: Any = None) -> AsyncIterator[str]:
        yield "partial"
        await asyncio.sleep(10)

    proc, send, _m = _processor()
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_slow))
    await proc.process(_event(), "sid")
    assert "Response timed out" in send.await_args_list[-1].args[2]


# ── process: mid-stream error ─────────────────────────────────────


async def test_process_error_mid_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, send, metrics = _processor()
    monkeypatch.setattr(
        proc.registry, "create_agent", lambda s: _agent(_gen(["ok"], raise_exc=RuntimeError("boom")))
    )
    await proc.process(_event(), "sid")
    metrics.inc.assert_any_call("message_processing_errors", {"channel": "web"})
    assert "Error occurred while processing" in send.await_args_list[-1].args[2]


# ── process: streaming timeout + error tails ──────────────────────


async def test_process_timeout_streams_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.message_processor.settings", SimpleNamespace(agent_token_timeout=0.05)
    )
    channel_obj = SimpleNamespace(send_stream=MagicMock(), ask_confirmation=AsyncMock(return_value=True))

    async def _slow(confirm_fn: Any = None, history: Any = None) -> AsyncIterator[str]:
        yield "partial"
        await asyncio.sleep(10)

    proc, send, _m = _processor(channel_obj=channel_obj)
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_slow))
    await proc.process(_event(), "sid")
    stream_calls = [c for c in send.await_args_list if c.kwargs.get("streaming") is True]
    assert any("Response timed out" in c.args[2] for c in stream_calls)


async def test_process_error_streams_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    channel_obj = SimpleNamespace(send_stream=MagicMock(), ask_confirmation=AsyncMock(return_value=True))
    proc, send, _m = _processor(channel_obj=channel_obj)
    monkeypatch.setattr(
        proc.registry, "create_agent", lambda s: _agent(_gen(["ok"], raise_exc=RuntimeError("boom")))
    )
    await proc.process(_event(), "sid")
    stream_calls = [c for c in send.await_args_list if c.kwargs.get("streaming") is True]
    assert any("Error occurred while processing" in c.args[2] for c in stream_calls)


# ── _manage_context ───────────────────────────────────────────────


async def test_manage_context_no_ctxmgr() -> None:
    proc, _s, _m = _processor(ctxmgr=None)
    out = await proc._manage_context("sid", [_msg("a", "user"), _msg("b", "assistant")])
    assert out == [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]


async def test_manage_context_empty() -> None:
    ctxmgr = MagicMock()
    ctxmgr.estimate_tokens = AsyncMock()
    proc, _s, _m = _processor(ctxmgr=ctxmgr)
    assert await proc._manage_context("sid", []) == []
    ctxmgr.estimate_tokens.assert_not_awaited()


async def test_manage_context_below_threshold() -> None:
    ctxmgr = MagicMock()
    ctxmgr._config = SimpleNamespace(max_tokens=1000, warning_threshold=0.8)
    ctxmgr.estimate_tokens = AsyncMock(return_value=100)
    proc, _s, metrics = _processor(ctxmgr=ctxmgr)
    out = await proc._manage_context("sid", [_msg("a")])
    assert out[0]["content"] == "a"
    metrics.observe.assert_any_call("context_window_pct", 10.0, {"session_id": "sid"})
    metrics.inc.assert_not_called()


async def test_manage_context_urgent_and_managed() -> None:
    ctxmgr = MagicMock()
    ctxmgr._config = SimpleNamespace(max_tokens=1000, warning_threshold=0.8)
    ctxmgr.estimate_tokens = AsyncMock(return_value=900)
    managed_dicts: list[Any] = [{"role": "user", "content": "summarized", "created_at": None, "metadata": {}}]
    ctxmgr.manage = AsyncMock(return_value=managed_dicts)
    proc, _s, metrics = _processor(ctxmgr=ctxmgr)
    repl: Any = proc.db.replace_session_messages
    out = await proc._manage_context("sid", [_msg("a")])
    assert out == managed_dicts
    repl.assert_awaited_once_with("sid", managed_dicts)
    metrics.inc.assert_any_call("context_window_urgent", {"session_id": "sid"})
    metrics.inc.assert_any_call("context_window_managed", {"session_id": "sid"})


async def test_manage_context_urgent_unmanaged() -> None:
    ctxmgr = MagicMock()
    ctxmgr._config = SimpleNamespace(max_tokens=1000, warning_threshold=0.8)
    ctxmgr.estimate_tokens = AsyncMock(return_value=900)
    msg_dicts_sentinel: list[Any] = []

    async def _manage(msgs: list[Any]) -> list[Any]:
        msg_dicts_sentinel.append(msgs)
        return msgs  # returns the same object -> "not managed"

    ctxmgr.manage = _manage
    proc, _s, metrics = _processor(ctxmgr=ctxmgr)
    repl: Any = proc.db.replace_session_messages
    out = await proc._manage_context("sid", [_msg("a")])
    assert out is msg_dicts_sentinel[0]
    metrics.inc.assert_any_call("context_window_urgent", {"session_id": "sid"})
    # no managed replacement happened, so no replace + no managed counter
    repl.assert_not_awaited()
    assert "context_window_managed" not in [c.args[0] for c in metrics.inc.call_args_list]


async def test_manage_context_zero_max_tokens() -> None:
    ctxmgr = MagicMock()
    ctxmgr._config = SimpleNamespace(max_tokens=0, warning_threshold=0.8)
    ctxmgr.estimate_tokens = AsyncMock(return_value=500)
    proc, _s, metrics = _processor(ctxmgr=ctxmgr)
    out = await proc._manage_context("sid", [_msg("a")])
    # ratio is 0 with zero max_tokens -> below threshold, returns dict form untouched
    metrics.observe.assert_any_call("context_window_pct", 0.0, {"session_id": "sid"})
    assert out[0]["content"] == "a"


# ── usage_mode ────────────────────────────────────────────────────


def test_usage_line_off_says_nothing() -> None:
    assert usage_line("off", {"prompt": 40, "completion": 12, "rounds": 2}) == ""


def test_usage_line_tokens_adds_up() -> None:
    assert usage_line("tokens", {"prompt": 40, "completion": 12, "rounds": 2}) == (
        "[tokens: 40 in / 12 out / 52 total]"
    )


def test_usage_line_full_counts_the_model_calls() -> None:
    line = usage_line("full", {"prompt": 40, "completion": 12, "rounds": 2})
    assert line.startswith("[tokens: 40 in / 12 out / 52 total]")
    assert "model calls: 2" in line


async def test_process_sends_the_usage_line_the_pref_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, send, _m = _processor(prefs={'usage_mode': 'tokens'})
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_gen(["Hel", "lo"])))
    await proc.process(_event(), "sid")
    assert send.await_args_list[-1].args[2] == "[tokens: 40 in / 12 out / 52 total]"
    prefs: Any = proc._get_pref
    assert [c.args[2] for c in prefs.await_args_list] == ["verbose", "trace", "think_level", "usage_mode"]


async def test_usage_line_is_a_separate_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reply is what gets stored as assistant history; a meter reading glued onto it would be
    re-read by the model as part of its own answer."""
    proc, send, _m = _processor(prefs={'usage_mode': 'full'})
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_gen(["Hel", "lo"])))
    await proc.process(_event(), "sid")
    sent = [c for c in send.await_args_list if c.kwargs.get("streaming") is False]
    assert sent[0].args[2] == "Hello"
    assert sent[1].args[2].startswith("[tokens:")
    assert sent[1].args[2] != sent[0].args[2]


async def test_process_stays_quiet_when_the_usage_pref_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, send, _m = _processor(prefs={})
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: _agent(_gen(["Hel", "lo"])))
    await proc.process(_event(), "sid")
    assert [c.args[2] for c in send.await_args_list] == ["Hello"]


async def test_the_three_channel_prefs_land_on_the_agent_before_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/verbose`, `/trace` and `/think` write preferences; the agent is what acts on them, so a
    run started with the defaults must not be able to keep the previous chatter."""
    proc, _send, _m = _processor(prefs={"verbose": "on", "trace": "on", "think_level": "low"})
    agent = _agent(_gen(["ok"]))
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: agent)
    await proc.process(_event(), "sid")
    assert agent.show_tool_progress is True
    assert agent.trace is True
    assert agent.think_level == "low"


async def test_unset_prefs_keep_the_modes_the_commands_report(monkeypatch: pytest.MonkeyPatch) -> None:
    proc, _send, _m = _processor(prefs={})
    agent = _agent(_gen(["ok"]))
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: agent)
    await proc.process(_event(), "sid")
    assert agent.show_tool_progress is False
    assert agent.trace is False
    assert agent.think_level == "high"


async def test_a_processor_without_a_pref_store_leaves_the_agent_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """ravencode and the CLI build agents directly; nothing there reads the gateway's prefs."""
    proc, send, _m = _processor()
    agent = _agent(_gen(["Hel", "lo"]))
    monkeypatch.setattr(proc.registry, "create_agent", lambda s: agent)
    await proc.process(_event(), "sid")
    assert agent.show_tool_progress is True
    assert send.await_args_list[-1].args[2] == "Hello"

"""Preferences must survive a restart and must not grow with the user count."""

from __future__ import annotations

import asyncio
import re
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from raven.core.agents.orchestrator import StatusEmitter
from raven.core.gateway.commands.settings import _PREF_KEYS
from raven.core.gateway.gateway import PREF_CACHE_MAX, PREFS_PLUGIN_ID, Gateway, orchestrator_report
from raven.core.models import IncomingMessage

ROOT = Path(__file__).resolve().parents[2]
_WRITE_RE = re.compile(r'set_pref\([^,]+,[^,]+,\s*"([a-z_]+)"')
_READ_RE = re.compile(r'get_pref\([^,]+,[^,]+,\s*"([a-z_]+)"')


class _FakeDB:
    """Stands in for the plugin_state table so the test sees what a restart really does."""

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    async def save_plugin_state(self, plugin_id: str, key: str, value: str) -> None:
        self.rows[f"{plugin_id}:{key}"] = value

    async def get_plugin_state(self, plugin_id: str, key: str) -> str | None:
        return self.rows.get(f"{plugin_id}:{key}")


class _NoChannels:
    async def get(self, channel_id: str) -> None:
        return None


class _Metrics:
    def inc(self, name: str, labels: dict[str, str] | None = None) -> None:
        return None


def _gateway(db: _FakeDB) -> Gateway:
    gateway = Gateway.__new__(Gateway)
    gateway.db = db
    gateway._prefs = OrderedDict()
    gateway._prefs_lock = threading.Lock()
    return gateway


def test_a_preference_survives_the_process(tmp_path_factory: pytest.TempPathFactory) -> None:
    async def run() -> None:
        db = _FakeDB()
        await _gateway(db).set_pref("telegram", "u1", "verbose", "on")
        restarted = _gateway(db)
        assert restarted._prefs == {}
        assert await restarted.get_pref("telegram", "u1", "verbose", "off") == "on"

    asyncio.run(run())


def test_a_preference_with_no_stored_value_keeps_its_default() -> None:
    async def run() -> None:
        gateway = _gateway(_FakeDB())
        assert await gateway.get_pref("telegram", "nobody", "trace", "off") == "off"

    asyncio.run(run())


def test_the_cache_is_bounded_by_users() -> None:
    """The old dict kept one entry per channel:user forever, so a public bot grew it until the
    restart that everyone notices as 'my settings went back to default'."""

    async def run() -> None:
        gateway = _gateway(_FakeDB())
        for i in range(PREF_CACHE_MAX + 50):
            await gateway.set_pref("telegram", f"u{i}", "usage_mode", "tokens")
        assert len(gateway._prefs) == PREF_CACHE_MAX
        assert await gateway.get_pref("telegram", "u0", "usage_mode", "off") == "tokens"

    asyncio.run(run())


def test_the_storage_key_names_the_gateway_its_own() -> None:
    async def run() -> None:
        db = _FakeDB()
        await _gateway(db).set_pref("discord", "u9", "think_level", "low")
        assert list(db.rows) == [f"{PREFS_PLUGIN_ID}:discord:u9:think_level"]

    asyncio.run(run())


def _event(metadata: dict[str, object] | None = None) -> IncomingMessage:
    return IncomingMessage(channel="telegram", user_id="u1", text="hi", metadata=dict(metadata or {}))


def test_mention_mode_answers_a_direct_message() -> None:
    async def run() -> None:
        gateway = _gateway(_FakeDB())
        assert await gateway._is_activated(_event({"chat_type": "private", "mentioned": False}))

    asyncio.run(run())


def test_mention_mode_waits_for_an_address_in_a_group() -> None:
    async def run() -> None:
        gateway = _gateway(_FakeDB())
        assert not await gateway._is_activated(_event({"chat_type": "group", "mentioned": False}))
        assert await gateway._is_activated(_event({"chat_type": "supergroup", "mentioned": True}))

    asyncio.run(run())


def test_always_mode_answers_a_group_that_never_mentioned_the_bot() -> None:
    async def run() -> None:
        gateway = _gateway(_FakeDB())
        await gateway.set_pref("telegram", "u1", "activation_mode", "always")
        assert await gateway._is_activated(_event({"chat_type": "group", "mentioned": False}))

    asyncio.run(run())


def test_a_channel_that_records_no_chat_type_is_left_alone() -> None:
    """webchat, email, irc and friends set nothing here. Guessing 'not mentioned' would silence
    every one of them the moment the default mention mode is applied."""

    async def run() -> None:
        gateway = _gateway(_FakeDB())
        assert await gateway._is_activated(_event({}))
        assert await gateway._is_activated(_event({"chat_id": "5", "username": "someone"}))

    asyncio.run(run())


def test_every_preference_a_command_writes_is_something_the_pipeline_reads() -> None:
    """A command that stores a preference nothing reads is a dead control: the operator types it,
    gets 'Verbose mode: on.' and nothing changes. This guard fails the build on the next one."""
    writers: dict[str, set[str]] = {}
    for f in (ROOT / "raven" / "core" / "gateway" / "commands").glob("*.py"):
        for key in _WRITE_RE.findall(f.read_text(encoding="utf-8")):
            writers.setdefault(key, set()).add(f.name)
    readers: dict[str, set[str]] = {}
    for f in (ROOT / "raven").rglob("*.py"):
        if "commands" in f.parts:
            continue
        for key in _READ_RE.findall(f.read_text(encoding="utf-8")):
            readers.setdefault(key, set()).add(f.name)
    assert set(writers) == set(_PREF_KEYS), f"commands write {sorted(writers)}"
    assert set(readers) == set(_PREF_KEYS), f"the pipeline reads {sorted(readers)}, commands write {sorted(_PREF_KEYS)}"
    assert readers["activation_mode"] == {"gateway.py"}
    agent_side = {"message_processor.py"}
    both = agent_side | {"gateway.py"}
    assert readers["verbose"] == readers["trace"] == readers["usage_mode"] == both
    assert readers["think_level"] == both, "the profile path must read the level too"


def test_the_preference_guard_reads_the_calls_it_claims_to() -> None:
    assert _WRITE_RE.findall('await gateway.set_pref(ch, uid, "verbose", setting)') == ["verbose"]
    assert _READ_RE.findall('mode = await self._get_pref(ch, uid, "usage_mode", "off")') == ["usage_mode"]
    assert _READ_RE.findall('await self._get_pref(channel, user_id)') == []

def _emitter() -> StatusEmitter:
    async def build() -> StatusEmitter:
        emitter = StatusEmitter(None)
        await emitter.tool_call("coder", "shell.run", {"command": "ls"})
        await emitter.tool_result("coder", "shell.run", "ok")
        await emitter.thinking("coder", "choosing a path")
        return emitter

    return asyncio.run(build())


def _result(tokens: int = 4821, iterations: int = 3, duration: float = 12.34) -> SimpleNamespace:
    return SimpleNamespace(
        tokens_used=tokens, iterations=iterations, duration=duration, content="the answer"
    )


def test_a_profile_run_reports_nothing_until_a_preference_asks() -> None:
    report = orchestrator_report(
        _emitter(), _result(), verbose=False, trace=False, usage_mode="off"
    )
    assert report == ""


def test_verbose_lists_the_tool_calls_a_profile_run_made() -> None:
    report = orchestrator_report(
        _emitter(), _result(), verbose=True, trace=False, usage_mode="off"
    )
    assert report.splitlines() == ["[coder] shell.run", "[coder] shell.run: ok"]
    # the thinking line is not a tool call: /verbose promises the calls, not the monologue
    assert "choosing a path" not in report


def test_trace_reports_the_run_from_the_numbers_the_result_kept() -> None:
    report = orchestrator_report(
        _emitter(), _result(), verbose=False, trace=True, usage_mode="off"
    )
    assert report == "[trace 3 iterations | 12.3s | 4821 tokens]"


def test_usage_of_a_profile_run_reports_the_total_it_actually_has() -> None:
    """The orchestrator counts tokens used, not an in/out split, so the line must say one
    number rather than claim a request that cost nothing."""
    report = orchestrator_report(
        _emitter(), _result(), verbose=False, trace=False, usage_mode="tokens"
    )
    assert report == "[tokens: 4821 total]"
    report = orchestrator_report(
        _emitter(), _result(), verbose=False, trace=False, usage_mode="full"
    )
    assert report.startswith("[tokens: 4821 total] ")
    assert "model calls: 3" in report


async def test_the_profile_path_reads_the_same_four_preferences() -> None:
    db = _FakeDB()
    gateway = _gateway(db)
    await gateway.set_pref("telegram", "u1", "think_level", "medium")
    await gateway.set_pref("telegram", "u1", "usage_mode", "tokens")
    await gateway.set_pref("telegram", "u1", "verbose", "on")
    await gateway.set_pref("telegram", "u1", "trace", "on")

    seen: dict[str, object] = {}

    async def execute(**kwargs: object) -> SimpleNamespace:
        seen.update(kwargs)
        return _result(tokens=100, iterations=1, duration=0.5)

    # the four collaborators the branch touches, stubbed through an untyped handle
    stub: Any = gateway
    stub._agent_orchestrator = SimpleNamespace(execute=execute)
    stub.channels = _NoChannels()
    sent: list[str] = []

    async def send(channel: str, session_id: str, text: str, **_kwargs: object) -> None:
        sent.append(text)

    stub._send = send
    stub._message_processor = SimpleNamespace(metrics=_Metrics())

    await gateway._handle_with_orchestrator(
        IncomingMessage(channel="telegram", user_id="u1", text="do the thing"), "sid", "coder"
    )

    context = seen["context"]
    assert isinstance(context, dict)
    assert "Plan briefly before you answer." in context["additional_context"]
    # the report travels as its own message after the answer, never glued onto it
    assert len(sent) == 2 and sent[0] == "the answer", sent
    assert sent[-1] == "[trace 1 iterations | 0.5s | 100 tokens]\n[tokens: 100 total]"

"""Preferences must survive a restart and must not grow with the user count."""

from __future__ import annotations

import asyncio
import re
import threading
from collections import OrderedDict
from pathlib import Path

import pytest

from raven.core.gateway.commands.settings import _PREF_KEYS
from raven.core.gateway.gateway import PREF_CACHE_MAX, PREFS_PLUGIN_ID, Gateway
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
    assert readers["verbose"] == readers["trace"] == readers["think_level"] == agent_side
    assert readers["usage_mode"] == agent_side


def test_the_preference_guard_reads_the_calls_it_claims_to() -> None:
    assert _WRITE_RE.findall('await gateway.set_pref(ch, uid, "verbose", setting)') == ["verbose"]
    assert _READ_RE.findall('mode = await self._get_pref(ch, uid, "usage_mode", "off")') == ["usage_mode"]
    assert _READ_RE.findall('await self._get_pref(channel, user_id)') == []

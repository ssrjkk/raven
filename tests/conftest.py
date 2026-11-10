from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import threading
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from raven.channels.base import BaseChannel
from raven.core.config import settings
from raven.core.db import Database
from raven.core.gateway.gateway import Gateway
from raven.core.llm import LLMProvider, LLMResponse
from raven.core.models import IncomingMessage, Message
from raven.core.plugin_loader import PluginLoader
from ravencode.runtime.plugins import get_plugin_registry


class MockLLMProvider(LLMProvider):
    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["Test response"]
        self.call_count = 0

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self.call_count += 1
        idx = min(self.call_count - 1, len(self.responses) - 1)
        return LLMResponse(content=self.responses[idx])

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        self.call_count += 1
        idx = min(self.call_count - 1, len(self.responses) - 1)
        for token in self.responses[idx].split():
            yield token + " "
            await asyncio.sleep(0)

    async def cleanup(self):
        pass


class MockChannel(BaseChannel):
    channel_id = "mock"

    def __init__(self):
        self.sent_messages: list[Message] = []
        self._handler = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send(self, session_id: str, message: Message):
        self.sent_messages.append(message)
        return message

    async def on_message(self, handler):
        self._handler = handler

    async def start(self):
        pass

    async def stop(self):
        pass

    async def health_check(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _isolate_plugin_registry() -> Iterator[None]:
    """Undo plugin registrations made during a test.

    ``get_plugin_registry()`` is process-wide and its tools are appended to MCP
    ``tools/list``, so a leaked plugin changes the tool count for every later test.
    """
    registry = get_plugin_registry()
    before = set(registry.plugins)
    yield
    for name in set(registry.plugins) - before:
        registry.unregister(name)


@pytest.fixture(autouse=True)
def _isolate_token_manager() -> Iterator[None]:
    """token_manager is process-wide and a bound AuthStore points at one test's database."""
    from raven.core.auth.tokens import token_manager

    token_manager.bind(None)
    token_manager._tokens.clear()
    yield
    token_manager.bind(None)
    token_manager._tokens.clear()


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _tracked_top_level_entries() -> frozenset[str]:
    """Top-level names the version control index owns, or an empty set when the tree is not a repository."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return frozenset()
    if listed.returncode != 0:
        return frozenset()
    names = (name.decode("utf-8", "replace") for name in listed.stdout.split(b"\0") if name)
    return frozenset({name.partition("/")[0] for name in names})


_TRACKED_TOP_LEVEL = _tracked_top_level_entries()


def _root_entries() -> set[str]:
    with os.scandir(_REPO_ROOT) as handle:
        return {entry.name for entry in handle}


@pytest.fixture(autouse=True)
def _repository_files_stay_put() -> Iterator[None]:
    """Fail the test that moved a tracked file out of the repository.

    Code that resolves the workspace root reaches this real tree, so a test whose patch no longer
    matches what that code reads relocates the operator's files for good; the ORGANIZE_FILES routine
    did exactly that to 17 root files from inside the gate.
    """
    if not _TRACKED_TOP_LEVEL:
        yield
        return
    before = _root_entries()
    yield
    after = _root_entries()
    if after == before:
        return
    missing = sorted(name for name in _TRACKED_TOP_LEVEL if not (_REPO_ROOT / name).exists())
    if missing:
        shown = ", ".join(missing[:5])
        pytest.fail(f"{len(missing)} tracked path(s) left the repository root: {shown}")


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr("raven.core.gateway.gateway.settings.default_model", "ollama/test")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "open")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.context_visibility", "public")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_allow_from", "")


@pytest.fixture
async def real_db(tmp_path) -> AsyncGenerator[Database, None]:
    db = Database(tmp_path / "test.db")
    await db.connect()
    yield db
    await db.disconnect()


@pytest.fixture
async def gateway(real_db: Database, mock_settings: None) -> AsyncGenerator[Gateway, None]:
    g = Gateway(db=real_db, plugin_loader=PluginLoader())
    g.llm._providers["ollama"] = MockLLMProvider(["Test response"])
    channel = MockChannel()
    await g.register_channel(channel)
    channel._handler = g.handle_message
    yield g
    await g.stop()


@pytest.fixture
def mcp_stdio(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any, str], Awaitable[list[dict[str, Any]]]]:
    """Run an MCP stdio server over a canned stdin transcript and return the frames it wrote."""

    async def _serve(server: Any, transcript: str) -> list[dict[str, Any]]:
        out = io.StringIO()
        monkeypatch.setattr("sys.stdin", io.StringIO(transcript))
        monkeypatch.setattr("sys.stdout", out)
        await asyncio.wait_for(server.run(), timeout=10)
        return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]

    return _serve


def _is_sqlite_worker(thread: threading.Thread) -> bool:
    target = getattr(thread, "_target", None)
    return (
        not thread.daemon
        and getattr(target, "__module__", "") == "aiosqlite.core"
        and getattr(target, "__qualname__", "") == "_connection_worker_thread"
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """An unclosed SQLite connection leaves a non-daemon thread that blocks interpreter exit.

    The process then prints its summary and hangs in threading._shutdown, which a gate sees only
    as a killed stage; naming the leak here is the difference between a timeout and a cause.
    """
    workers = [t for t in threading.enumerate() if _is_sqlite_worker(t)]
    for thread in workers:
        thread.join(timeout=5.0)
    leaked = [t for t in workers if t.is_alive()]
    if leaked:
        session.exitstatus = 1
        names = ", ".join(t.name for t in leaked)
        print(f"\n[leak] {len(leaked)} aiosqlite worker(s) outlived the tests: {names}", flush=True)

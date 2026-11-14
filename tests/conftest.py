from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import threading
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterable, Iterator
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


@pytest.fixture(autouse=True)
def _runtime_switches_stay_where_the_test_left_them() -> Iterator[None]:
    """A test that moves a switch moves it for the rest of the run, and the next file pays for it.

    `apply_runtime_switch` and `refresh_settings_from_env` both write the settings singleton and
    rebuild the consumers that bound their value at import, and `middleware.rate_limiter` is one
    per-address budget shared by every `TestClient` in the process: the watcher test that set
    `RATE_LIMIT_MAX=33` left every later batch running on a budget a single test had chosen. Measured
    with a probe over `tests/test_aios_bridge.py`, `tests/test_aios_e2e.py` and
    `tests/cli/test_gateway_runner.py` in one process -- 45 limiter checks against the one
    `testclient` key -- so a leak that spends 45 requests turns later calls into 429s depending on
    which file ran first, which is how the same suite passes on a slow machine and fails on a fast one.

    The exported names are snapshotted with the settings because they are a second copy of the same
    switch, and only the env half leaks silently: `monkeypatch.delenv(name, raising=False)` records
    nothing for a name the machine does not have, so a value `write_env_value` puts into `os.environ`
    outlives the test that caused it. Measured -- `tests/core/test_config_watcher.py` left
    `DEFAULT_MODEL` exported, and two files later `refresh_settings_from_env()` inside an unrelated
    test adopted it and moved `settings.default_model`, so the guard below blamed the innocent file.
    """
    from raven.core import middleware
    from raven.core.config import runtime_switches

    switches = runtime_switches()
    before = {switch.attr: getattr(settings, switch.attr) for switch in switches}
    exported = {switch.env_name: os.environ.get(switch.env_name) for switch in switches}
    limiter = middleware.rate_limiter
    budget = (limiter.max_requests, limiter.window)
    yield
    moved = sorted(attr for attr, value in before.items() if getattr(settings, attr) != value)
    leaked = {name: value for name, value in exported.items() if os.environ.get(name) != value}
    for attr in moved:
        setattr(settings, attr, before[attr])
    for name, value in leaked.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if middleware.rate_limiter is not limiter:
        moved.append("middleware.rate_limiter")
        middleware.rate_limiter = limiter
    if (limiter.max_requests, limiter.window) != budget:
        moved.append("middleware.rate_limiter budget")
        (limiter.max_requests, limiter.window) = budget
    left_behind = sorted(moved + [f"{name} exported" for name in leaked])
    assert not left_behind, (
        f"this test left {left_behind} set for the rest of the run; take the `switch_env` fixture from "
        "tests/core/conftest.py, or pin what the product code exports with `pin_env_names` from this "
        "file, so the move is undone"
    )


@pytest.fixture
def pin_env_names() -> Iterator[Callable[[Iterable[str]], None]]:
    """Take the named env vars out of the process for the test and put back exactly what was there.

    ``monkeypatch.delenv(name, raising=False)`` registers no undo for a name that is absent, so a value
    the product code exports during the test -- ``write_env_value`` and ``apply_runtime_switch`` both
    write ``os.environ`` themselves -- survives the test and reaches every file that runs after it. The
    snapshot records ``None`` for an absent name and deletes it again on the way out.
    """
    taken: dict[str, str | None] = {}

    def pin(names: Iterable[str]) -> None:
        for name in names:
            if name in taken:
                continue
            taken[name] = os.environ.get(name)
            os.environ.pop(name, None)

    yield pin

    for name, value in taken.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(scope="session", autouse=True)
def _database_stays_out_of_the_repository(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """`create_aios_app()` binds an AuthStore at `settings.resolved_db_path` on startup, and that bind
    lands after the per-test `token_manager.bind(None)`, so the ordering race cannot be won: every
    bearer session issued by `tests/test_aios_bridge.py` and `tests/test_aios_e2e.py` was written into
    the operator's real `data/raven.db`. Measured across one full 16-stage gate: `auth_sessions` went
    451 -> 527 rows (+76: `bridge-admin` +66, `e2e-admin` +8, `e2e-user` +2) and the table that decides
    whether a caller is revoked was 100% test residue. Redirecting `settings.db_path` for the whole
    run puts every consumer of `resolved_db_path` -- auth, tasks, routines, monitors, the data dir the
    outbox and sessions live in -- under this run's temp directory, which is how the log is isolated.
    """
    db_dir = tmp_path_factory.mktemp("runtime-db")
    settings.db_path = str(db_dir / "raven.db")
    yield


@pytest.fixture(scope="session", autouse=True)
def _runtime_logs_stay_out_of_the_repository(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Eleven product entry points call `setup_logging()` with no path, which resolves to
    `settings.resolved_log_file` — the repository's own `data/raven.log`. Every test that ran one
    of them appended to the operator's live log (697 mock-channel lines from a single gate run),
    and rotation then deletes real history on a 30-day timer. Point the default destination at
    this run's temp directory; callers that pass an explicit path are unaffected.
    """
    from loguru import logger

    log_dir = tmp_path_factory.mktemp("runtime-logs")
    settings.log_file = str(log_dir / "pytest-raven.log")
    yield
    logger.remove()


_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_DB = _REPO_ROOT / "data" / "raven.db"


def _repo_db_state() -> tuple[Any, ...]:
    """What a write to the repository's own database changes: the main file's size and mtime, plus the
    size of its write-ahead log, which a WAL-mode transaction appends to before any checkpoint."""
    state: list[Any] = []
    for path in (_REPO_DB, Path(f"{_REPO_DB}-wal")):
        try:
            stat = path.stat()
        except OSError:
            state.append(None)
            continue
        state.append((stat.st_size, stat.st_mtime_ns))
    return tuple(state)


@pytest.fixture(autouse=True)
def _operator_database_is_not_a_test_fixture() -> Iterator[None]:
    """Fail the test that writes the operator's database, naming it.

    The session redirect is what stops this happening; this is what proves it stopped, because a test
    that hands a repository path straight to a store bypasses `settings.db_path` entirely.
    """
    before = _repo_db_state()
    yield
    after = _repo_db_state()
    if after != before:
        pytest.fail(
            f"this test modified the operator's database at {_REPO_DB} -- point it at a tmp_path "
            "database instead of the repository one"
        )


_OPERATOR_ENV_FILES = (_REPO_ROOT / ".env", Path.home() / ".raven" / ".env")


def _operator_env_state() -> tuple[Any, ...]:
    state: list[Any] = []
    for path in _OPERATOR_ENV_FILES:
        try:
            stat = path.stat()
        except OSError:
            state.append(None)
            continue
        state.append((stat.st_size, stat.st_mtime_ns))
    return tuple(state)


@pytest.fixture(scope="session", autouse=True)
def _env_files_stay_out_of_the_repository(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """`apply_runtime_switch` writes to the last existing env-file candidate, and on an install that is
    the operator's own `.env`. Measured: one run of `tests/core/test_admin_api.py` replaced
    `DEFAULT_MODEL` there with the value a test had just posted, and the file is gitignored, so nothing
    put it back. Appending this run's temp file to the candidate list makes it the highest precedence,
    so a write that was never pinned lands where the run can throw it away. A test that pins the file
    itself still wins, because its monkeypatch is applied after this session patch.
    """
    from raven.core import config as config_module

    target = tmp_path_factory.mktemp("runtime-env") / ".env"
    target.write_text("", encoding="utf-8")
    before = list(config_module._ENV_FILE_CANDIDATES)
    config_module._ENV_FILE_CANDIDATES = [*before, str(target)]
    yield
    config_module._ENV_FILE_CANDIDATES = before


@pytest.fixture(autouse=True)
def _operator_env_file_is_not_a_test_fixture() -> Iterator[None]:
    """Fail the test that writes an operator env file, naming it.

    The redirect is what stops the common case; this is what proves it stopped, because a test that
    hands a repository path straight to `write_env_value(..., env_path=)` bypasses the candidates.
    """
    before = _operator_env_state()
    yield
    after = _operator_env_state()
    if after != before:
        pytest.fail(
            "this test modified an operator env file ("
            + ", ".join(str(path) for path in _OPERATOR_ENV_FILES)
            + ") -- point it at a tmp_path file instead"
        )


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


@pytest.fixture
def grant_permission() -> Iterator[Callable[[str, Any], None]]:
    """Hand a permission to a role through the role table, for the duration of one test.

    The narrow request guards answer `rbac.has_permission`, so granting a right to a role that does
    not normally hold it is the only way to tell a check that asks the table from one that compares
    the role name at the call site.
    """
    from raven.core.auth.models import Permission, Role
    from raven.core.auth.rbac import rbac

    granted: list[tuple[Role, Permission]] = []

    def _grant(role: str, permission: Permission) -> None:
        key = Role(role)
        rbac.add_role_permission(key, permission)
        granted.append((key, permission))

    yield _grant

    for key, permission in granted:
        rbac.remove_role_permission(key, permission)


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

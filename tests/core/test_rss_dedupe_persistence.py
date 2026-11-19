"""The RSS dedupe has to survive the process that learned the entries.

`check_rss` used to keep seen guids in a module-level dict with a seven-day TTL, so a gateway restart
answered the first poll of every RSS monitor with the whole feed as new. The state is rows in
`rss_seen_items` now, one per (entry, monitor), which is what these tests hold: a restart changes
nothing, a genuinely new entry still alerts, the first poll of a monitor baselines instead of shouting,
being seen is a fact per monitor rather than a global one, and nothing in the checker keeps a second
copy of the state.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

import pytest

from raven.core.db import Database
from raven.core.http_client import client_manager
from raven.core.monitor.checkers import rss as rss_module
from raven.core.monitor.engine import MonitorEngine
from raven.core.monitor.models import Monitor, MonitorType
from raven.core.monitor.store import MonitorStore
from raven.core.retention import POLICIES, RetentionSweeper

MONITOR_ID = "rss-1"
URL = "https://example.com/feed.xml"


def _feed(*guids: str) -> str:
    items = "".join(
        f"<item><title>Post {guid}</title><link>https://example.com/{guid}</link><guid>{guid}</guid></item>"
        for guid in guids
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def _monitor(monitor_id: str = MONITOR_ID) -> Monitor:
    return Monitor(id=monitor_id, name="feed", type=MonitorType.RSS, target=URL)


class _Server:
    """One fake feed for a whole test: the guid list is mutable, so a test can make an entry arrive later."""

    def __init__(self, *guids: str) -> None:
        self.guids = list(guids)

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        class _Resp:
            text = _feed(*self.guids)

        return _Resp()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    """Serves the feed and switches the SSRF guard off, because the URL here is not a real host."""
    srv = _Server("g1", "g2")

    async def _request(*args: Any, **kwargs: Any) -> Any:
        return await srv.request()

    monkeypatch.setattr(client_manager, "request", _request)
    monkeypatch.setattr(rss_module, "validate_url", lambda _url: None)
    return srv


def _restart() -> Any:
    """A gateway restart, as far as this checker can feel one: the module loads again, so no process state
    survives it and only what the database recorded is left to read."""
    return importlib.reload(rss_module)


def _serve_again(monkeypatch: pytest.MonkeyPatch, restarted: Any, srv: _Server) -> None:
    async def _request(*args: Any, **kwargs: Any) -> Any:
        return await srv.request()

    monkeypatch.setattr(client_manager, "request", _request)
    monkeypatch.setattr(restarted, "validate_url", lambda _url: None)


async def _seen_guids(store: MonitorStore, monitor_id: str = MONITOR_ID) -> list[str]:
    rows = await store._fetchall("SELECT guid FROM rss_seen_items WHERE monitor_id = ? ORDER BY guid", (monitor_id,))
    return [str(row["guid"]) for row in rows]


async def test_the_first_poll_baselines_the_feed_instead_of_alerting_it(server: _Server, tmp_path: Path) -> None:
    """The rule the design turns on: no rows for this monitor yet means the feed is not new, only unseen."""
    store = MonitorStore(tmp_path / "monitors.db")
    try:
        await store.save_monitor(_monitor())
        assert await rss_module.check_rss(_monitor(), store) is None
        assert await _seen_guids(store) == ["g1", "g2"]
    finally:
        await store.close()


async def test_a_restarted_gateway_does_not_report_the_whole_feed_as_new(
    server: _Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MonitorStore(tmp_path / "monitors.db")
    try:
        await store.save_monitor(_monitor())
        assert await rss_module.check_rss(_monitor(), store) is None

        restarted = _restart()
        _serve_again(monkeypatch, restarted, server)
        assert await restarted.check_rss(_monitor(), store) is None
    finally:
        await store.close()


async def test_a_restarted_gateway_still_reports_an_entry_that_is_actually_new(
    server: _Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the fix: remembering the feed must not swallow real news. One guid arrives after
    the baseline poll and before the poll that follows the restart."""
    store = MonitorStore(tmp_path / "monitors.db")
    try:
        await store.save_monitor(_monitor())
        await rss_module.check_rss(_monitor(), store)

        server.guids.append("g3")
        restarted = _restart()
        _serve_again(monkeypatch, restarted, server)

        alert = await restarted.check_rss(_monitor(), store)
        assert alert is not None and "Post g3" in alert, alert
        assert "Post g1" not in alert and "Post g2" not in alert, alert
        assert await _seen_guids(store) == ["g1", "g2", "g3"]
    finally:
        await store.close()


async def test_being_seen_is_a_fact_per_monitor_not_a_global_one(
    server: _Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The primary key is (guid, monitor_id): a second monitor on the same feed baselines for itself instead
    of inheriting the first one's memory, which would leave it reporting nothing forever."""
    store = MonitorStore(tmp_path / "monitors.db")
    try:
        await store.save_monitor(_monitor())
        await store.save_monitor(_monitor("rss-2"))
        await rss_module.check_rss(_monitor(), store)

        assert await rss_module.check_rss(_monitor("rss-2"), store) is None
        assert await _seen_guids(store, "rss-2") == ["g1", "g2"]
        assert await rss_module.check_rss(_monitor("rss-2"), store) is None

        server.guids.append("g9")
        alert = await rss_module.check_rss(_monitor("rss-2"), store)
        assert alert is not None and "Post g9" in alert, alert
        assert await _seen_guids(store, "rss-2") == ["g1", "g2", "g9"]
        assert await _seen_guids(store) == ["g1", "g2"], "the second monitor wrote into the first one's rows"
    finally:
        await store.close()


async def test_the_engine_is_the_call_site_that_has_to_pass_the_store(server: _Server, tmp_path: Path) -> None:
    """Production reaches the checker only through `_run_item`, and an engine that failed to hand it the
    store would keep every test above green — `_run_item` catches the exception and reports nothing."""
    path = tmp_path / "monitors.db"
    engine = MonitorEngine(path)
    try:
        await engine._store.save_monitor(_monitor())
        assert await engine._run_item(_monitor()) is None
        assert await _seen_guids(engine._store) == ["g1", "g2"]

        server.guids.append("g3")
        restarted = MonitorEngine(path)
        try:
            alert = await restarted._run_item(_monitor())
        finally:
            await restarted._store.close()

        assert alert is not None and "Post g3" in alert, alert
        assert "Post g1" not in alert, alert
    finally:
        await engine._store.close()


async def test_the_checker_keeps_no_second_copy_of_the_seen_state(tmp_path: Path) -> None:
    """Two sources of truth for one fact is the defect class this fix exists to end: a duplicate dict would
    keep every test above green while the database quietly stopped being the authority."""
    for name in ("_seen_guids", "_seen_timestamps", "_seen_lock", "_SEEN_TTL_SECONDS", "_cleanup_stale_guids"):
        assert not hasattr(rss_module, name), f"{name} is back in the checker"

    store = MonitorStore(tmp_path / "monitors.db")
    try:
        await store.save_monitor(_monitor())
        await rss_module.check_rss(_monitor(), store)
    finally:
        await store.close()

    for name in ("_seen_guids", "_seen_timestamps", "_cleanup_stale_guids"):
        assert not hasattr(rss_module, name), f"the poll restored {name}"


async def test_both_creation_paths_describe_the_same_dedupe_table(tmp_path: Path) -> None:
    """`Database` bootstraps the schema and `MonitorStore` creates the table on its own connection, which is
    the path a monitors-only install takes. The sweep reads `seen_at` as a database timestamp here, so a
    column drifting in one of the two definitions would break aging for the other one."""
    bootstrap = tmp_path / "bootstrap.db"
    database = Database(bootstrap)
    await database.connect()
    try:
        core_rows = await database._fetchall("PRAGMA table_info(rss_seen_items)")
    finally:
        await database.disconnect()

    store = MonitorStore(tmp_path / "store.db")
    try:
        await store._conn()
        store_rows = await store._fetchall("PRAGMA table_info(rss_seen_items)")
    finally:
        await store.close()

    def _shape(rows: list[Any]) -> list[tuple[str, str, int, int]]:
        return [(str(r["name"]), str(r["type"]).upper(), int(r["notnull"]), int(r["pk"])) for r in rows]

    assert _shape(core_rows) == _shape(store_rows), (core_rows, store_rows)
    assert _shape(core_rows)[0][1] == "TEXT", _shape(core_rows)


def _aged_out() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - 400 * 86_400))


async def test_the_sweep_ages_and_caps_the_dedupe_rows_the_policy_claims(tmp_path: Path) -> None:
    """The window an entry stays unseen became the telemetry window, so the sweep has to reach this table by
    both rules: old rows by `seen_at`, a runaway feed by the per-monitor cap. The cap orders and deletes by
    `guid` because the table has no id column, and it is the newest rows that have to survive."""
    store = MonitorStore(tmp_path / "monitors.db")
    try:
        await store.save_monitor(_monitor())
        await store._execute(
            "INSERT INTO rss_seen_items (guid, monitor_id, seen_at) VALUES (?, ?, ?)",
            ("stale", MONITOR_ID, _aged_out()),
        )
        for guid in ("new0", "new1", "new2"):
            await store._execute(
                "INSERT INTO rss_seen_items (guid, monitor_id, seen_at) VALUES (?, ?, datetime('now'))",
                (guid, MONITOR_ID),
            )

        sweeper = RetentionSweeper(tmp_path / "monitors.db", telemetry_days=30, telemetry_rows=2, history_days=0)
        removed = await sweeper.run_once()
        assert removed == {"rss_seen_items": 2}, removed
        assert await _seen_guids(store) == ["new1", "new2"], "the cap kept the wrong rows"
    finally:
        await store.close()


def test_the_dedupe_table_is_a_telemetry_policy_now() -> None:
    """`unused` was the honest label while nothing read the table. Every RSS poll reads it, so the registry
    has to name the knob that ages it and the knob that bounds it."""
    policy = POLICIES["rss_seen_items"]
    assert policy.kind == "telemetry", policy
    assert policy.age_column == "seen_at" and policy.parent_column == "monitor_id", policy
    assert policy.id_column == "guid", policy
    assert policy.unit == {"sqlite": "sql_datetime", "postgresql": "timestamp"}, policy

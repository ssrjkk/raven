"""Emit the payloads the console's status surfaces answer, so the SPA is tested against the server's contract.

`web/e2e/dashboard.spec.ts`, `rate-limit.spec.ts` and `monitors.spec.ts` stub `/api/admin/system/status`,
`/api/status`, `/api/metrics` and `/api/monitor/list`. Until this file existed every one of those stubs was
typed by hand, which is the hole that let `/api/health` crash the shipped dashboard behind a green suite
(see `scripts/gen_health_fixture.py`). The hand-typed payloads were already wrong in ways nobody could see:
`version: "0.4.8"` while the route answered the string `"1.0.0"`, and a monitor list whose items the server
has never emitted with the fields the page reads.

So the payloads here come out of the routers the gateway mounts, wired the way `gateway_runner` wires them:
a real `Database` on a throwaway file, the real `ChannelManager` with the real webchat channel registered,
`AgentRegistry.setup_defaults()` called by `Gateway.start()`, the monitor engine built by
`register_all_monitors()`, and metrics warmed with the calls the gateway itself makes. Each export is
annotated with the SPA's own declaration, so the emitted literal stops compiling when the two disagree.

Usage:
    python scripts/gen_api_fixtures.py --write
    python scripts/gen_api_fixtures.py              # compare, exit non-zero on drift
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import pathlib
import shutil
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime, tzinfo

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TARGET = REPO / "web" / "e2e" / "fixtures" / "api.ts"

FROZEN_MODEL = "ollama/llama3"
"""What the route answers for `model` comes from `settings.default_model`, which production fills by probing
whichever providers this machine has keys for. The attribute is set the way `apply_runtime_switch` sets it —
without writing an env file — so the emitted payload says the same thing on the operator's box, in CI and
inside the pytest process, where the settings object was built long before this script ran."""

FROZEN_MONITOR_ID = "0000000000000000"
"""`MonitorStore` assigns a uuid4 hex per row, and a byte-for-byte gate cannot follow it."""

FROZEN_CHECKED_AT = 1_700_000_000.0
"""`last_check.checked_at` is a `time.time()` stamp, the same obstacle `gen_health_fixture.py` freezes."""

FROZEN_NOW = 1_700_000_000
"""The analytics answers are stamped with `datetime.now(UTC)` and bucketed from it, so a byte-for-byte
gate cannot read a wall clock. One frozen instant, advanced by the snapshot interval the same way a
running engine advances its own, keeps the emitted series the same on every machine."""


class _FrozenClock:
    """The `datetime` attribute of the analytics modules, with the wall clock taken out of it.

    Both modules import `datetime` by name, so replacing the module attribute is what the running
    interpreter would do at import time — every `now()` in the request path answers from here.
    """

    def __init__(self, ts: int) -> None:
        self.ts = ts

    def now(self, tz: tzinfo | None) -> datetime:
        return datetime.fromtimestamp(self.ts, tz)


_SCRATCH = pathlib.Path(tempfile.mkdtemp(prefix="raven-gen-api-fixtures-"))
"""Every row this script writes lands here; the tree the operator runs is never touched."""


@contextlib.contextmanager
def _state_as_found() -> Iterator[None]:
    """The routers read two process-wide singletons; the gate runs this file inside a live test session.

    `settings` and `metrics` are the same objects every other test sees, so the model pin and the warmed
    counters are handed back the way `test_spa_health_contract.py` hands back the health registry. The
    analytics modules keep the frozen clock and the throwaway engine in module attributes too, and an
    engine whose database file this function deletes before returning is the last thing a later test
    should be handed.

    The registries are emptied, not merely saved, and that is the whole difference between a fixture that
    reproduces and one that does not: by the time `tests/unit` reaches this render, thousands of earlier
    tests have already recorded `db_query` latencies and `llm_complete` counters into the same
    dictionaries, and `/api/metrics` answers with all of them. The byte-for-byte gate then blamed the
    committed fixture for what was really the test order, and it failed only in the full run -- a fresh
    process emitted the three warmed families and nothing else.
    """
    import raven.core.analytics as analytics_module
    import raven.core.analytics_api as analytics_api_module
    from raven.core.config import settings
    from raven.core.metrics import metrics

    model = settings.default_model
    clock, engine = analytics_module.datetime, analytics_api_module.datetime  # type: ignore[attr-defined]
    analytics_engine = analytics_api_module._engine
    counters, latencies, errors = (
        dict(metrics._counters),
        {k: list(v) for k, v in metrics._latencies.items()},
        dict(metrics._errors),
    )
    try:
        settings.default_model = FROZEN_MODEL
        metrics._counters, metrics._latencies, metrics._errors = {}, {}, {}
        yield
    finally:
        analytics_module.datetime = clock  # type: ignore[attr-defined]
        analytics_api_module.datetime = engine  # type: ignore[attr-defined]
        analytics_api_module._engine = analytics_engine
        settings.default_model = model
        metrics._counters, metrics._latencies, metrics._errors = counters, latencies, errors


def _freeze(monitor: dict[str, object]) -> dict[str, object]:
    monitor["id"] = FROZEN_MONITOR_ID
    last_check = monitor.get("last_check")
    if isinstance(last_check, dict):
        last_check["checked_at"] = FROZEN_CHECKED_AT
    return monitor


async def payloads() -> dict[str, object]:
    """The four answers, taken from the routers a running gateway mounts."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    import raven.core.analytics as analytics_module
    import raven.core.analytics_api as analytics_api_module
    from raven.channels.webchat.channel import WebChatChannel
    from raven.core.admin_api import create_admin_router
    from raven.core.analytics import AnalyticsEngine
    from raven.core.analytics_api import create_analytics_router, set_analytics_engine
    from raven.core.db import Database
    from raven.core.features import FeatureFlags
    from raven.core.gateway.gateway import Gateway
    from raven.core.metrics import metrics
    from raven.core.monitor.engine import MonitorEngine
    from raven.core.monitor.store import MonitorStore
    from raven.core.ops_api import create_ops_router
    from raven.core.plugin_loader import PluginLoader
    from raven.core.status_api import create_status_router
    from raven.monitors.register_all import register_all_monitors

    db_path = str(_SCRATCH / "raven.db")
    db = Database(pathlib.Path(db_path))
    await db.connect()
    loader = PluginLoader()
    for plugin_dir in sorted((REPO / "raven" / "plugins").iterdir(), key=lambda path: path.name):
        loader.load_from_dir(plugin_dir)
    gateway = Gateway(db, loader)
    await gateway.register_channel(WebChatChannel(db))

    store = MonitorStore(db_path)
    engine = MonitorEngine(store)
    await register_all_monitors(engine)

    app = FastAPI()
    app.include_router(create_status_router(gateway, loader, asyncio.Event()))
    app.include_router(create_ops_router(gateway, FeatureFlags()))
    app.include_router(create_admin_router(lambda: gateway.channels, lambda: gateway.registry, lambda: gateway))
    app.include_router(create_analytics_router())
    app.state.monitor_engine = engine

    with _state_as_found():
        # The names, the labels and the arithmetic come from the calls the gateway makes: `gateway.py:576`
        # counts a received message under its channel, `gateway.py:726` a sent one, and `instrumented.py:28`
        # observes every provider request under its provider and model. Warmed without those labels, the
        # emitted payload spelled keys no running gateway answers — and the label-less histogram it built
        # raised inside the gateway's own next LLM request.
        provider, _, _ = FROZEN_MODEL.partition("/")
        metrics.inc("messages_received", {"channel": "webchat"})
        metrics.inc("messages_sent", {"channel": "webchat"})
        metrics.observe("llm_request", 0.42, {"provider": provider, "model": FROZEN_MODEL})
        metrics.observe("llm_request", 1.37, {"provider": provider, "model": FROZEN_MODEL})
        # `tool_registry.py:177` counts every call under its tool and category, `:187` the successes and
        # `:203` the errors — labelled, which is the spelling `/analytics` has to resolve.
        metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
        metrics.inc("tool_calls_success_total", {"tool": "read_file"})

        # `Gateway.start()` is how the running flag is set in production; with only webchat registered it opens
        # no socket, so the emitted `running: true` is the route's answer rather than a value written into it.
        await gateway.start()

        # The engine production builds on the same file (`gateway_runner.py:439`), pointed at one clock so
        # the two snapshots land on instants a byte-for-byte gate can reproduce.
        frozen = _FrozenClock(FROZEN_NOW)
        analytics_module.datetime = frozen  # type: ignore[assignment, attr-defined]
        analytics_api_module.datetime = frozen  # type: ignore[assignment, attr-defined]
        analytics = AnalyticsEngine(db_path, snapshot_interval=3600)
        await analytics.start()
        set_analytics_engine(analytics)
        await analytics._snapshot()
        frozen.ts += 60
        for _ in range(2):
            metrics.inc("tool_calls_total", {"tool": "read_file", "category": "fs"})
            metrics.inc("tool_calls_success_total", {"tool": "read_file"})
        metrics.inc("tool_calls_total", {"tool": "bash", "category": "exec"})
        metrics.inc("tool_calls_error_total", {"tool": "bash", "reason": "exception"})
        metrics.inc("messages_received", {"channel": "webchat"})
        metrics.inc("messages_sent", {"channel": "webchat"})
        metrics.observe("llm_request", 0.97, {"provider": provider, "model": FROZEN_MODEL})
        await analytics._snapshot()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gen") as client:
            status = (await client.get("/api/status")).json()
            system_status = (await client.get("/api/admin/system/status")).json()
            metrics_snapshot = (await client.get("/api/metrics")).json()
            monitor_list = (await client.get("/api/monitor/list?limit=50&offset=0")).json()
            analytics_full = (await client.get("/api/analytics/full")).json()

        await analytics.stop()
        await gateway.stop()
    await store.close()
    await db.disconnect()

    monitor_list["items"] = [_freeze(item) for item in monitor_list["items"]]
    return {
        "status": status,
        "systemStatus": system_status,
        "metrics": metrics_snapshot,
        "monitorList": monitor_list,
        "analyticsFull": analytics_full,
    }


_TYPES = {
    "status": "StatusData",
    "systemStatus": "SystemStatusData",
    "metrics": "MetricsSnapshot",
    "monitorList": "MonitorListData",
    "analyticsFull": "AnalyticsFullData",
}

_ANSWERS = """\
/* Generated by scripts/gen_api_fixtures.py from the answers of GET /api/status,
   GET /api/admin/system/status, GET /api/metrics, GET /api/monitor/list and GET /api/analytics/full
   -- do not edit by hand. Regenerate with: python scripts/gen_api_fixtures.py --write */

import type {
  AnalyticsFullData, MetricsSnapshot, MonitorListData, StatusData, SystemStatusData,
} from "../../src/api/types";

"""

# The literal is emitted untyped and then assigned: the routers answer fields the SPA does not read
# (`use_memory`, `effective_interval`, `group`), and an annotation on the literal itself would reject them
# for the wrong reason. Required and typed fields still have to agree, which is the claim being made.
_TYPING = """\
const {name}Answer = {body};
export const {name}: {kind} = {name}Answer;
"""


def render() -> str:
    try:
        answers = asyncio.run(payloads())
    finally:
        shutil.rmtree(_SCRATCH, ignore_errors=True)
    blocks = "\n\n".join(
        _TYPING.format(name=name, kind=_TYPES[name], body=json.dumps(answers[name], indent=2, sort_keys=True))
        for name in ("status", "systemStatus", "metrics", "monitorList", "analyticsFull")
    )
    return f"{_ANSWERS}{blocks}\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    text = render()
    if args.write:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {TARGET}")
        return 0
    if not TARGET.is_file():
        print(f"{TARGET} is missing — run python scripts/gen_api_fixtures.py --write")
        return 1
    if TARGET.read_text(encoding="utf-8") != text:
        print(f"{TARGET} no longer matches what the status routes answer; regenerate it")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

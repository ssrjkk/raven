"""The request budget belongs to the API, and a refusal has to name the moment it frees.

Measured over http on the shipped gateway on 2026-11-18: one cold console navigation is 15 requests, 10 of them
files already on disk (`/assets/*.js`, the fonts, the manifest), so two reloads spent the whole
per-IP budget of 60 and the third answered the *application shell* with `429` and raw JSON — the operator
lost the console to a limit meant for programmatic callers, and nothing in the browser could recover it
inside the window. The 429 that did arrive carried `retry_after` in the body only, so `curl`, browsers and
any proxy in front were told to retry whenever they liked.

Every promise below is asserted against an app wired the way `raven/cli/gateway_runner.py` wires it: the
same middleware, `mount_spa` last, the `/dashboard` mount built from the same class. The exemption is a
declaration a handler makes about itself (`raven.core.spa.BUNDLE_SERVED_ATTR`), so these tests fail the day
the middleware consults a list of paths instead of the router — including by the tests' own plants, which is
what makes the first test evidence rather than optimism.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Route

from raven.channels.webchat.channel import WebChatChannel
from raven.core import middleware as middleware_module
from raven.core.db import Database
from raven.core.middleware import RateLimiter
from raven.core.spa import BUNDLE_SERVED_ATTR, BundleFiles, mount_spa

NAVIGATION = ("/", "/assets/app.js", "/fonts/IBMPlexSans-latin.woff2", "/sw.js", "/monitors", "/dashboard/")
"""One cold load of the console, in the order a browser asks: the shell, a hashed chunk, a font, the worker,
a client-side route, and the separate webchat surface."""


def _bundle(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    files = {
        "index.html": b"<!doctype html><title>the app</title>",
        "assets/app.js": b"console.log('bundle')",
        "fonts/IBMPlexSans-latin.woff2": b"wOF2\x00\x00\x00\x01font-bytes",
        "sw.js": b"self.addEventListener('install',()=>{});",
    }
    for rel, data in files.items():
        target = dist / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return dist


def _gateway_client(
    app: FastAPI, dist: Path, monkeypatch: pytest.MonkeyPatch, *, max_requests: int, window: float = 60.0
) -> TestClient:
    """The limiter as a global http middleware, a dynamic route, `/dashboard`, and the SPA registered last."""
    app.middleware("http")(middleware_module.rate_limit_middleware)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/dashboard", BundleFiles(directory=str(dist), html=True), name="dashboard")
    assert mount_spa(app, dist) is True
    monkeypatch.setattr(
        middleware_module, "rate_limiter", RateLimiter(max_requests=max_requests, window_seconds=window)
    )
    return TestClient(app)


def _route_for(app: FastAPI, path: str) -> Route:
    """The router entry serving ``path``, held as the object the middleware reads the marker off.

    Typed as a route rather than patted off ``app.routes`` with ``getattr``: an app that stopped serving the
    path fails by name here instead of yielding an object with no attribute and letting the marker assertion
    below decide about nothing.
    """
    for route in app.routes:
        if isinstance(route, Route) and route.path == path:
            return route
    msg = f"the app serves nothing at {path!r}, so there is no handler whose declaration can be read"
    raise AssertionError(msg)


def test_a_day_of_navigating_the_console_never_spends_the_api_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """6 loads = 36 requests against a budget of 5, and the budget stays whole: the files answer from
    themselves and a client route still gets the shell. A 429 here means something started charging the bundle
    again — which is the defect, not a limit that was set too low."""
    client = _gateway_client(FastAPI(), _bundle(tmp_path), monkeypatch, max_requests=5)
    for load in range(6):
        for path in NAVIGATION:
            response = client.get(path)
            assert response.status_code == 200, (
                f"load {load}: {path} answered {response.status_code}: {response.text[:80]}"
            )
            assert b"Too many requests" not in response.content
    assert client.get("/api/health").status_code == 200, "the budget was spent by the bundle after all"


def test_the_exemption_is_a_declaration_and_not_a_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`/sw.js` is a file in the bundle, but this app answers it from a plain route that declared nothing — so
    it is charged, and the refusal is right. The same budget keeps the shell free one request later. If the
    middleware ever decides by path or extension instead of by the handler, this test goes red with nothing
    else changing."""
    app = FastAPI()
    dist = _bundle(tmp_path)

    @app.get("/sw.js")
    async def a_route_that_happens_to_serve_a_file() -> dict[str, bool]:
        return {"dynamic": True}

    client = _gateway_client(app, dist, monkeypatch, max_requests=2)
    assert client.get("/sw.js").json() == {"dynamic": True}
    assert client.get("/sw.js").status_code == 200
    assert client.get("/sw.js").status_code == 429, "a bundle-shaped path escaped the budget without declaring itself"
    assert client.get("/").status_code == 200, "the handler that did declare itself should never have been charged"


def test_a_shell_that_stops_declaring_itself_is_charged_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The plant that makes the first test evidence: lift the marker off the catch-all and the same traffic
    trips 429 on `/`. So the exemption really is read from the router, and the day someone renames or stops
    setting it the budget starts eating the console again — and says so here."""
    app = FastAPI()
    client = _gateway_client(app, _bundle(tmp_path), monkeypatch, max_requests=5)
    catch_all = _route_for(app, "/{full_path:path}")
    assert getattr(catch_all.endpoint, BUNDLE_SERVED_ATTR, None) is True
    monkeypatch.delattr(catch_all.endpoint, BUNDLE_SERVED_ATTR)

    statuses = [client.get("/").status_code for _ in range(10)]
    assert statuses[0] == 200
    assert 429 in statuses, "the shell stayed free with its declaration removed: the budget is not read from the router"


def test_the_address_the_console_is_opened_at_is_exempt_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gateway does not build its app out of nothing: `api_app = webchat.app`, and that app answers `/` from
    its own route (`raven/channels/webchat/channel.py:150`) with the built document plus a CSP canary. It is
    registered before `mount_spa`, so it wins `/` from the marked catch-all -- and measured over http on the
    live gateway it was the last bundle-shaped route the budget still ate: `/` answered the operator `429` JSON
    while the fonts and deep links around it kept serving. So the app here is the channel's own."""
    client = _gateway_client(_webchat_app(), _bundle(tmp_path), monkeypatch, max_requests=5)
    for load in range(6):
        for path in NAVIGATION:
            response = client.get(path)
            assert response.status_code == 200, f"load {load}: {path} answered {response.status_code}"
    assert client.get("/api/health").status_code == 200, "six console loads spent the API budget again"


def test_the_webchat_document_declares_itself() -> None:
    """Its own route, its own declaration, so the day the marker is renamed or lifted the message names this
    handler instead of leaving the operator to discover it by watching `/` answer JSON."""
    root = _route_for(_webchat_app(), "/")
    assert getattr(root.endpoint, BUNDLE_SERVED_ATTR, None) is True


def _webchat_app() -> FastAPI:
    """The application the gateway really serves. Registering the webchat routes touches no database."""
    return WebChatChannel(cast("Database", SimpleNamespace())).app


def test_the_api_still_costs_the_budget_and_says_when_to_come_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exempting the bundle must not soften the limit for programmatic callers: the API keeps refusing, and the
    refusal now carries the header every client and every proxy actually reads."""
    client = _gateway_client(FastAPI(), _bundle(tmp_path), monkeypatch, max_requests=3, window=60.0)
    assert [client.get("/api/health").status_code for _ in range(3)] == [200, 200, 200]
    refused = client.get("/api/health")
    assert refused.status_code == 429
    header = refused.headers.get("Retry-After")
    assert header is not None, "429 without Retry-After tells the client to retry whenever it likes"
    assert header.isdigit(), f"Retry-After has to be a number of seconds, got {header!r}"
    assert 1 <= int(header) <= 60, header
    assert json.loads(refused.content)["retry_after"] == int(header), "the body and the header promise different waits"
    assert client.get("/").status_code == 200, "the console has to stay reachable while the API is refusing"


def test_the_refusal_names_the_real_refill_moment_not_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sliding window frees its next slot as soon as the oldest charge ages out, so quoting the whole window
    on every refusal made a client wait up to a minute for a slot that was already open. The table is aged by
    hand because the promise is about the arithmetic, not about sleeping."""
    client = _gateway_client(FastAPI(), _bundle(tmp_path), monkeypatch, max_requests=2, window=60.0)
    limiter = middleware_module.rate_limiter

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    refused = client.get("/api/health")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) == 60, "a window only just spent has the whole window left to run"

    bucket = limiter._buckets["testclient"]
    bucket[:] = [stamp - 45.0 for stamp in bucket]
    refused = client.get("/api/health")
    assert refused.status_code == 429
    quoted = int(refused.headers["Retry-After"])
    assert 15 <= quoted <= 16, f"the slot opens in 15s but the answer promised {quoted}s"


def test_a_budget_of_zero_refuses_without_promising_a_moment_that_never_comes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A budget of zero is not something settings can produce — `raven/core/config.py:365` rejects it and the
    runtime switch at `raven/core/config.py:564` floors it at 1 — but it is the degenerate input the limiter's
    own arithmetic has to survive: refusing is right, crashing while composing the refusal is not, and an
    address with no charges has no oldest one to age."""
    client = _gateway_client(FastAPI(), _bundle(tmp_path), monkeypatch, max_requests=0, window=60.0)
    refused = client.get("/api/health")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) == 60


def test_both_bundle_mounts_declare_themselves_on_the_class() -> None:
    """The gateway builds its own `BundleFiles` for `/dashboard`, outside `mount_spa`. A marker set in
    `__init__` or on one instance would cover the SPA's `/assets` mount and leave that one charged, so the
    declaration belongs on the class."""
    assert getattr(BundleFiles, BUNDLE_SERVED_ATTR, None) is True


def test_retry_after_is_zero_while_the_budget_lasts_and_never_exceeds_the_window() -> None:
    """The helper's own edges, asserted rather than assumed: 0 for an address with slots left, and for a
    refused one a value inside the window — which is what the middleware's `max(1, ceil(...))` rests on."""
    limiter = RateLimiter(max_requests=2, window_seconds=5.0)

    async def probe() -> tuple[float, float, float]:
        key = "203.0.113.9"
        before = await limiter.retry_after(key)
        await limiter.check(key)
        one_slot_left = await limiter.retry_after(key)
        await limiter.check(key)
        return (before, one_slot_left, await limiter.retry_after(key))

    before, one_slot_left, spent = asyncio.run(probe())
    assert (before, one_slot_left) == (0.0, 0.0)
    assert 0.0 < spent <= 5.0
    assert spent == pytest.approx(5.0, abs=0.2)

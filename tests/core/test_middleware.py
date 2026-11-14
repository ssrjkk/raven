from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from loguru import logger

from raven.core import middleware
from raven.core.auth.tokens import token_manager
from raven.core.config import settings
from raven.core.metrics import metrics
from raven.core.middleware import (
    RateLimiter,
    auth_middleware,
    build_rate_limiter,
    client_ip,
    request_id_middleware,
    sanitize_metric_path,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_id_middleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "pong"}

    return app


def _make_full_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(auth_middleware)

    @app.post("/api/echo")
    async def echo() -> dict[str, str]:
        return {"ok": "echo"}

    @app.get("/api/read")
    async def read() -> dict[str, str]:
        return {"ok": "read"}

    @app.post("/api/auth/login")
    async def login() -> dict[str, str]:
        return {"ok": "login"}

    @app.post("/api/webhooks/generic")
    async def webhook() -> dict[str, str]:
        return {"ok": "webhook"}

    @app.get("/api/chat/search")
    async def chat_search() -> dict[str, str]:
        return {"ok": "search"}

    @app.get("/api/email/inbox")
    async def email_inbox() -> dict[str, str]:
        return {"ok": "inbox"}

    @app.get("/api/email/config")
    async def email_config() -> dict[str, str]:
        return {"ok": "config"}

    @app.get("/api/insights/workspace")
    async def insights() -> dict[str, str]:
        return {"ok": "insights"}

    @app.get("/api/rag/stats")
    async def rag_stats() -> dict[str, str]:
        return {"ok": "rag"}

    @app.get("/api/collab/sessions")
    async def collab_sessions() -> dict[str, str]:
        return {"ok": "collab"}

    @app.get("/api/voice/speakers")
    async def voice_speakers() -> dict[str, str]:
        return {"ok": "voice"}

    @app.get("/api/analytics/overview")
    async def analytics_overview() -> dict[str, str]:
        return {"ok": "analytics"}

    @app.get("/api/metrics/project")
    async def metrics_project() -> dict[str, str]:
        return {"ok": "metrics"}

    @app.get("/api/knowledge/stats")
    async def knowledge_stats() -> dict[str, str]:
        return {"ok": "knowledge"}

    @app.get("/api/ab/experiments")
    async def ab_experiments() -> dict[str, str]:
        return {"ok": "ab"}

    @app.get("/api/cicd/runs")
    async def cicd_runs() -> dict[str, str]:
        return {"ok": "cicd"}

    @app.get("/api/debug/state")
    async def debug_state() -> dict[str, str]:
        return {"ok": "debug"}

    @app.get("/api/metrics/prometheus")
    async def metrics_prom() -> dict[str, str]:
        return {"ok": "metrics"}

    @app.get("/api/stream")
    async def stream() -> dict[str, str]:
        return {"ok": "stream"}

    @app.get("/api/sse/events/sessions")
    async def sse_events() -> dict[str, str]:
        return {"ok": "sse"}

    @app.get("/api/workflows/templates")
    async def workflows_templates() -> dict[str, str]:
        return {"ok": "workflows"}

    @app.get("/api/monitor/list")
    async def monitor_list() -> dict[str, str]:
        return {"ok": "monitor"}

    @app.get("/api/monitor/slo")
    async def monitor_slo() -> dict[str, str]:
        return {"ok": "slo"}

    @app.get("/api/routine/list")
    async def routine_list() -> dict[str, str]:
        return {"ok": "routine"}

    @app.get("/api/task/list")
    async def task_list() -> dict[str, str]:
        return {"ok": "task"}

    @app.get("/api/code/list")
    async def code_list() -> dict[str, str]:
        return {"ok": "code"}

    @app.get("/api/status")
    async def status() -> dict[str, str]:
        return {"ok": "status"}

    @app.get("/api/agents")
    async def agents() -> dict[str, str]:
        return {"ok": "agents"}

    @app.get("/api/tools/policy")
    async def tools_policy() -> dict[str, str]:
        return {"ok": "policy"}

    return app


def test_generates_correlation_id_on_response() -> None:
    client = TestClient(_make_app())
    resp = client.get("/ping")
    assert resp.status_code == 200
    cid = resp.headers.get("X-Correlation-ID")
    assert cid is not None
    assert len(cid) == 32


def test_passthrough_existing_correlation_id() -> None:
    client = TestClient(_make_app())
    cid = uuid.uuid4().hex
    resp = client.get("/ping", headers={"X-Correlation-ID": cid})
    assert resp.status_code == 200
    assert resp.headers.get("X-Correlation-ID") == cid


class TestApiMutationGuard:
    def test_anonymous_mutation_rejected(self) -> None:
        client = TestClient(_make_full_app())
        assert client.post("/api/echo").status_code == 401
        assert client.put("/api/echo").status_code == 401
        assert client.delete("/api/echo").status_code == 401

    def test_anonymous_read_is_asked_for_a_credential(self) -> None:
        client = TestClient(_make_full_app())
        assert client.get("/api/read").status_code == 401

    async def test_user_token_may_not_write_an_unlisted_path(self) -> None:
        """A `user` token names a caller, not a key: an unlisted write is refused, not implied."""
        token = await token_manager.create_token("u1", "user")
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_raven_key_allowed(self) -> None:
        from raven.core.config import settings

        key = settings.web_secret_key.get_secret_value()
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", headers={"X-Raven-Key": key})
        assert resp.status_code == 200

    def test_invalid_token_rejected(self) -> None:
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", headers={"Authorization": "Bearer bogus-token"})
        assert resp.status_code == 401

    def test_auth_login_public(self) -> None:
        client = TestClient(_make_full_app())
        assert client.post("/api/auth/login").status_code == 200

    def test_webhooks_public(self) -> None:
        client = TestClient(_make_full_app())
        assert client.post("/api/webhooks/generic").status_code == 200

    @pytest.mark.asyncio
    async def test_garbage_body_still_blocked_before_parse(self) -> None:
        # mutation guard runs before body parsing — even invalid JSON is rejected unauthenticated
        client = TestClient(_make_full_app())
        resp = client.post("/api/echo", content=b"{not json", headers={"content-type": "application/json"})
        assert resp.status_code == 401


class TestPrivateReadGuard:
    def test_private_read_rejected_anonymous_when_secured(self) -> None:
        from raven.core.config import settings

        if not settings.web_secret_key:
            pytest.skip("web_secret_key not set")
        client = TestClient(_make_full_app())
        for path in (
            "/api/chat/search",
            "/api/collab/sessions",
            "/api/email/inbox",
            "/api/email/config",
            "/api/insights/workspace",
            "/api/rag/stats",
            "/api/voice/speakers",
            "/api/analytics/overview",
            "/api/metrics/project",
            "/api/knowledge/stats",
            "/api/ab/experiments",
            "/api/cicd/runs",
            "/api/debug/state",
            "/api/sse/events/sessions",
            "/api/stream",
            "/api/metrics/prometheus",
            "/api/workflows/templates",
            "/api/monitor/list",
            "/api/monitor/slo",
            "/api/routine/list",
            "/api/task/list",
            "/api/code/list",
            "/api/status",
            "/api/agents",
            "/api/tools/policy",
        ):
            assert client.get(path).status_code == 401, path

    async def test_private_read_allowed_with_bearer(self) -> None:
        token = await token_manager.create_token("u1", "user")
        client = TestClient(_make_full_app())
        for path in (
            "/api/chat/search",
            "/api/collab/sessions",
            "/api/email/inbox",
            "/api/email/config",
            "/api/insights/workspace",
            "/api/rag/stats",
            "/api/voice/speakers",
            "/api/analytics/overview",
            "/api/metrics/project",
            "/api/knowledge/stats",
            "/api/ab/experiments",
            "/api/cicd/runs",
            "/api/debug/state",
            "/api/sse/events/sessions",
            "/api/stream",
            "/api/metrics/prometheus",
            "/api/workflows/templates",
            "/api/monitor/list",
            "/api/monitor/slo",
            "/api/routine/list",
            "/api/task/list",
            "/api/code/list",
            "/api/status",
            "/api/agents",
        ):
            assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 200, path

    async def test_tools_policy_needs_more_than_a_session(self) -> None:
        # /api/tools/policy rewrites the tool allowlist, so it is an admin endpoint, not a read one
        user = await token_manager.create_token("u1", "user")
        admin = await token_manager.create_token("a1", "admin")
        client = TestClient(_make_full_app())
        assert client.get("/api/tools/policy", headers={"Authorization": f"Bearer {user}"}).status_code == 403
        assert client.get("/api/tools/policy", headers={"Authorization": f"Bearer {admin}"}).status_code == 200


def test_sanitize_metric_path_collapses_ids() -> None:
    assert sanitize_metric_path("/api/task/abc123def456") == "/api/task/{id}"
    assert sanitize_metric_path("/api/sessions/42") == "/api/sessions/{id}"
    assert sanitize_metric_path("/api/monitor/list") == "/api/monitor/list"
    assert sanitize_metric_path("/api/code/DEADBEEF1234/steps") == "/api/code/{id}/steps"


def _request_from(peer: str, xff: str | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [] if xff is None else [(b"x-forwarded-for", xff.encode())],
        "client": (peer, 12345),
        "server": ("test", 80),
        "scheme": "http",
        "query_string": b"",
    }
    return Request(scope)


def test_client_ip_uses_xff_from_loopback_peer() -> None:
    assert client_ip(_request_from("127.0.0.1", "203.0.113.7, 10.0.0.2")) == "203.0.113.7"


def test_client_ip_ignores_xff_from_external_peer() -> None:
    # 203.0.113.0/24 is a documentation range: `ipaddress` calls it private, but it is not a proxy
    # anybody installed, so a caller using it as its peer still cannot choose the address we log.
    assert client_ip(_request_from("203.0.113.9", "198.51.100.7")) == "203.0.113.9"


def test_client_ip_uses_xff_from_a_docker_network_peer() -> None:
    # The shipped compose stack reaches the gateway from Traefik on 172.16.0.0/12, commonly above the
    # 172.19 the old prefix list stopped at. Treat it as a stranger and every visitor shares one bucket.
    assert client_ip(_request_from("172.20.0.4", "203.0.113.7")) == "203.0.113.7"


def test_client_ip_uses_the_peer_when_there_is_no_proxy_header() -> None:
    assert client_ip(_request_from("203.0.113.9")) == "203.0.113.9"


def test_client_ip_honours_xff_from_a_stranger_once_a_proxy_is_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trust_forwarded_for", True)
    assert client_ip(_request_from("8.8.8.8", "203.0.113.7")) == "203.0.113.7"


def test_a_peer_that_is_not_an_address_cannot_spoof_one() -> None:
    assert client_ip(_request_from("unknown", "203.0.113.7")) == "unknown"


class TestHttpRateLimiter:
    async def test_the_budget_comes_from_the_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "rate_limit_max", 7)
        monkeypatch.setattr(settings, "rate_limit_window", 13)
        limiter = build_rate_limiter()
        assert limiter.max_requests == 7
        assert limiter.window == 13.0

    async def test_the_allowance_refills_as_the_window_slides(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=0.05)
        assert await limiter.check("1.1.1.1")
        assert await limiter.check("1.1.1.1")
        assert not await limiter.check("1.1.1.1")
        # Windows sleep granularity is ~16 ms, so the wait has to dwarf the window rather than edge past it.
        await asyncio.sleep(0.2)
        assert await limiter.check("1.1.1.1")

    async def test_one_address_does_not_spend_another_s_budget(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60.0)
        assert await limiter.check("1.1.1.1")
        assert await limiter.check("2.2.2.2")

    async def test_an_address_that_stopped_talking_is_forgotten(self) -> None:
        limiter = RateLimiter(max_requests=10, window_seconds=0.01, prune_interval=0.0)
        assert await limiter.check("1.1.1.1")
        await asyncio.sleep(0.2)
        assert await limiter.check("2.2.2.2")
        assert "1.1.1.1" not in limiter._buckets

    async def test_a_request_still_in_its_window_survives_a_prune(self) -> None:
        limiter = RateLimiter(max_requests=10, window_seconds=60.0, prune_interval=0.0)
        assert await limiter.check("1.1.1.1")
        assert await limiter.check("2.2.2.2")
        assert "1.1.1.1" in limiter._buckets

    async def test_the_table_is_rescanned_on_the_cadence_not_on_every_request(self) -> None:
        limiter = RateLimiter(max_requests=10, window_seconds=0.01, prune_interval=3600.0)
        assert await limiter.check("1.1.1.1")
        await asyncio.sleep(0.05)
        assert await limiter.check("2.2.2.2")
        assert "1.1.1.1" in limiter._buckets, "every request paid for a full scan"

    async def test_a_stale_key_dies_once_the_prune_interval_elapses(self) -> None:
        limiter = RateLimiter(max_requests=10, window_seconds=0.01, prune_interval=0.02)
        assert await limiter.check("1.1.1.1")
        await asyncio.sleep(0.05)
        assert "1.1.1.1" in limiter._buckets
        assert await limiter.check("2.2.2.2")
        assert "1.1.1.1" not in limiter._buckets


class TestRateLimitMiddleware:
    async def test_the_reply_quotes_the_configured_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=7.0)
        monkeypatch.setattr(middleware, "rate_limiter", limiter)
        metrics.clear()

        async def call_next(_request: Request) -> Response:
            return JSONResponse({"ok": True})

        allowed = await middleware.rate_limit_middleware(_request_from("203.0.113.5"), call_next)
        blocked = await middleware.rate_limit_middleware(_request_from("203.0.113.5"), call_next)
        assert allowed.status_code == 200
        assert blocked.status_code == 429
        assert json.loads(blocked.body)["retry_after"] == 7

    async def test_the_blocked_counter_carries_no_per_caller_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limiter = RateLimiter(max_requests=0, window_seconds=60.0)
        monkeypatch.setattr(middleware, "rate_limiter", limiter)
        metrics.clear()

        async def call_next(_request: Request) -> Response:
            return JSONResponse({"ok": True})

        for peer in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
            assert (await middleware.rate_limit_middleware(_request_from(peer), call_next)).status_code == 429
        snapshot = metrics.snapshot()
        assert snapshot.get("raven_http_rate_limited_total") == 3
        assert not [key for key in snapshot if "ip=" in key], "one series per address is a memory leak"

    async def test_the_refused_address_still_reaches_the_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        limiter = RateLimiter(max_requests=0, window_seconds=60.0)
        monkeypatch.setattr(middleware, "rate_limiter", limiter)
        records: list[str] = []

        async def call_next(_request: Request) -> Response:
            return JSONResponse({"ok": True})

        sink = logger.add(records.append, level="WARNING", format="{message}")
        try:
            await middleware.rate_limit_middleware(_request_from("203.0.113.5"), call_next)
        finally:
            logger.remove(sink)
        assert "203.0.113.5" in "".join(records)

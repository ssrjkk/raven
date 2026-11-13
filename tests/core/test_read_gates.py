"""A read of gateway data needs a caller; only a short declared list answers without one.

The rule used to be a hand-kept list of 31 prefixes that were *private*, and everything it forgot
answered anybody who knew the URL: `/api/dream/stats`, `/api/memory/backups`,
`/api/v1/patterns/run` (which reads up to 500 workspace files), `/api/v1/projects/{id}/insights`,
the session event stream, 15 more. It is now the other way round — `DATA_SCOPES` plus
`PUBLIC_READ_PREFIXES` — so an endpoint is private the moment it is mounted.

The two sweeps below walk the gateway's own declared route table rather than a list written here,
so a router added next week is covered without anybody remembering to add a test.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from raven.core.auth.tokens import token_manager
from raven.core.config import settings
from raven.core.middleware import (
    _PUBLIC_PATHS,
    MUTATING_METHODS,
    PUBLIC_READ_PREFIXES,
    _in_data_scope,
    _prefix_match,
    auth_middleware,
)

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_OPERATOR_KEY = "operator-key-under-test"

# Reads the old list forgot, measured off `scripts/route_surface.py` before the rule was inverted.
# Each one answered an unauthenticated caller on a port that may face the internet.
_FORGOTTEN_READS = (
    "/api/dream/stats",
    "/api/dream/status",
    "/api/memory/backups",
    "/api/v1/commands/contextual",
    "/api/v1/patterns/checks",
    "/api/v1/patterns/run",
    "/api/v1/projects/x/insights",
    "/api/v1/scaffold/plans",
    "/api/v1/scaffold/plans/x",
    "/api/web-search/providers",
    "/events/sessions",
    "/api/sessions",
    "/api/messages/x",
)


def _load() -> Any:
    name = "route_surface_for_read_gates"
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / "route_surface.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


surface = _load()


def _concrete(path: str) -> str:
    """A callable path: every `{parameter}` filled with a literal, so one stub serves it.

    The middleware decides on the path string alone, so a concrete sibling behaves exactly like the
    template it came from.
    """
    return re.sub(r"\{[^}]+\}", "x", path)


def _is_private_read(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return False
    return _in_data_scope(path) and not any(_prefix_match(path, prefix) for prefix in PUBLIC_READ_PREFIXES)


@pytest.fixture(scope="module")
def gateway_reads() -> list[str]:
    reads = {
        _concrete(path)
        for method, path, owner in surface.declared_routes()
        if method not in MUTATING_METHODS and method not in ("WEBSOCKET", "OPTIONS") and owner != surface.DAEMON_KEY
    }
    return sorted(reads)


@pytest.fixture(scope="module")
def client(gateway_reads: list[str]) -> TestClient:
    app = FastAPI()
    app.middleware("http")(auth_middleware)

    async def _ok() -> dict[str, bool]:
        return {"ok": True}

    for path in gateway_reads:
        app.add_api_route(path, _ok, methods=["GET"])
    return TestClient(app)


@pytest.fixture(autouse=True)
def _operator_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "web_secret_key", SecretStr(_OPERATOR_KEY))


class TestForgottenReads:
    """The endpoints the old private-prefix list left open, asserted by name."""

    @pytest.mark.parametrize("path", _FORGOTTEN_READS)
    def test_anonymous_caller_is_asked_for_a_credential(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 401, path

    @pytest.mark.parametrize("path", _FORGOTTEN_READS)
    async def test_an_account_reaches_it_instead(self, client: TestClient, path: str) -> None:
        token = await token_manager.create_token(f"reader:{path}", "user")
        assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 200, path


class TestReadGateSweep:
    def test_the_sweep_covers_a_real_surface(self, gateway_reads: list[str]) -> None:
        # A rule that gated nothing would let every assertion below pass by vacuity.
        assert len(gateway_reads) > 100
        assert sum(1 for path in gateway_reads if _is_private_read(path)) > len(gateway_reads) // 2

    def test_no_private_read_answers_an_anonymous_caller(self, client: TestClient, gateway_reads: list[str]) -> None:
        answered = [path for path in gateway_reads if _is_private_read(path) and client.get(path).status_code != 401]
        assert answered == []

    def test_every_declared_public_read_answers(self, client: TestClient, gateway_reads: list[str]) -> None:
        for prefix in PUBLIC_READ_PREFIXES:
            paths = [path for path in gateway_reads if _prefix_match(path, prefix)]
            assert paths, f"{prefix} declares a public read that no router serves"
            for path in paths:
                assert client.get(path).status_code == 200, path

    def test_static_delivery_still_loads_for_a_browser_with_no_token(
        self, client: TestClient, gateway_reads: list[str]
    ) -> None:
        # Outside the data scopes the gateway hands out files, not data: the webchat page and the
        # OpenAPI surface. Refusing these would lock everybody out of the login screen.
        open_paths = [path for path in gateway_reads if not _in_data_scope(path) or path in _PUBLIC_PATHS]
        assert "/" in open_paths
        for path in open_paths:
            assert client.get(path).status_code == 200, path

    def test_a_public_read_grants_its_siblings_nothing(self) -> None:
        # `PUBLIC_READ_PREFIXES` lists `/api/health`; a path that merely starts with it is somebody
        # else's router and stays private. Matched as a whole segment, exactly like the write table.
        app = FastAPI()
        app.middleware("http")(auth_middleware)

        async def _ok() -> dict[str, bool]:
            return {"ok": True}

        for path in ("/api/health", "/api/health-history"):
            app.add_api_route(path, _ok, methods=["GET"])
        probe = TestClient(app)
        assert probe.get("/api/health").status_code == 200
        assert probe.get("/api/health-history").status_code == 401

    def test_a_path_that_merely_starts_like_a_scope_is_static_delivery(self) -> None:
        # `/apifoo` is not under `/api`. The scopes are whole segments, so a mount that collides on a
        # letter cannot quietly lose the static delivery the login screen needs.
        app = FastAPI()
        app.middleware("http")(auth_middleware)

        async def _ok() -> dict[str, bool]:
            return {"ok": True}

        for path in ("/api/dream/stats", "/apifoo"):
            app.add_api_route(path, _ok, methods=["GET"])
        probe = TestClient(app)
        assert probe.get("/api/dream/stats").status_code == 401
        assert probe.get("/apifoo").status_code == 200

    def test_a_cors_preflight_is_answered_without_a_credential(self, client: TestClient) -> None:
        # A preflight carries no Authorization header by design; asking for one here would break
        # every credentialed cross-origin call before it ever reaches a route.
        assert client.options("/api/dream/stats").status_code != 401

    async def test_a_credential_alone_clears_the_read_gate(self, client: TestClient, gateway_reads: list[str]) -> None:
        token = await token_manager.create_token("reader", "user")
        headers = {"Authorization": f"Bearer {token}"}
        still_asked = [
            path
            for path in gateway_reads
            if _is_private_read(path) and client.get(path, headers=headers).status_code == 401
        ]
        assert still_asked == []

    def test_the_operator_key_reads_the_whole_declared_surface(
        self, client: TestClient, gateway_reads: list[str]
    ) -> None:
        denied = [
            path
            for path in gateway_reads
            if client.get(path, headers={"X-Raven-Key": _OPERATOR_KEY}).status_code != 200
        ]
        assert denied == []


class TestNoUnsecuredState:
    def test_an_empty_secret_does_not_open_a_private_read(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `Settings.model_post_init` mints a key when none is configured, so "local mode" was never
        # a state a running gateway could be in. The read rule no longer consults it.
        monkeypatch.setattr(settings, "web_secret_key", SecretStr(""))
        assert client.get("/api/dream/stats").status_code == 401

    def test_a_fresh_settings_object_always_holds_a_secret(self, tmp_path: pathlib.Path) -> None:
        from raven.core.config import SafeSecretStr, Settings

        instance = Settings(db_path=str(tmp_path / "raven.db"), web_secret_key=SafeSecretStr(""))
        assert len(instance.web_secret_key.get_secret_value()) >= 32

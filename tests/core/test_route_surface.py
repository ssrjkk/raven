"""The audit in `scripts/route_surface.py` as a build gate, plus the daemon's own credential rule.

`scripts/route_surface.py` builds every router the gateway mounts, which takes a few seconds, so the
surface is measured once per module and every claim below comes off that single build.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from raven.core.middleware import MUTATING_METHODS
from raven.gateway.daemon import RavenFlowDaemon

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load() -> Any:
    name = "route_surface"
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / "route_surface.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


surface = _load()


@pytest.fixture(scope="module")
def routes() -> list[tuple[str, str, str]]:
    return list(surface.declared_routes())


@pytest.fixture(scope="module")
def writes(routes: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    return [route for route in routes if route[0] in MUTATING_METHODS]


@pytest.fixture(scope="module")
def daemon_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    return TestClient(RavenFlowDaemon(port=0, data_dir=tmp_path_factory.mktemp("ravenflow")).app)


class TestSurfaceAudit:
    def test_the_writes_are_what_the_tables_say(self, routes: list[tuple[str, str, str]]) -> None:
        assert surface.check(routes) == []

    def test_every_mounted_router_is_audited(self, routes: list[tuple[str, str, str]]) -> None:
        assert surface.mounted_names() <= {owner for _, _, owner in routes} | {"webchat.app"}

    def test_the_write_table_grants_nothing_the_surface_does_not_serve(
        self, writes: list[tuple[str, str, str]]
    ) -> None:
        # A prefix with no route behind it is a promise the code does not keep: it would silently
        # cover whatever gets mounted there next.
        for prefix in surface.USER_MUTATING_PERMISSIONS:
            assert any(surface._prefix_match(path, prefix) for _, path, _ in writes), prefix

    def test_a_plain_account_writes_only_where_a_module_was_opened_on_purpose(
        self, routes: list[tuple[str, str, str]], writes: list[tuple[str, str, str]]
    ) -> None:
        exposed = {(method, path) for method, path, _ in surface.user_reachable_writes(routes)}
        for method, path, owner in writes:
            if (method, path) in exposed:
                assert owner in surface.EXPOSED_WRITE_ROUTERS, f"{method} {path} from {owner}"


class TestDaemonCredentialRule:
    """The daemon answers nothing without a credential — `/health` excepted, by design."""

    def test_every_declared_read_refuses_an_anonymous_call(
        self, daemon_client: TestClient, routes: list[tuple[str, str, str]]
    ) -> None:
        gated = [path for method, path, owner in routes if owner == surface.DAEMON_KEY and method == "GET"]
        assert [p for p in gated if p != "/health"]
        for path in gated:
            expected = 200 if path == "/health" else 401
            assert daemon_client.get(path).status_code == expected, path

    def test_a_socket_without_a_credential_never_opens(
        self, daemon_client: TestClient, routes: list[tuple[str, str, str]]
    ) -> None:
        sockets = [path for method, path, owner in routes if method == "WEBSOCKET" and owner == surface.DAEMON_KEY]
        assert sockets == ["/ws"]
        with pytest.raises(WebSocketDisconnect):
            with daemon_client.websocket_connect(sockets[0]):
                pass

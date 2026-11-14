"""The audit in `scripts/route_surface.py` as a build gate, the daemon's own credential rule, and the
sockets the console opens.

`scripts/route_surface.py` builds every router the gateway mounts, which takes a few seconds, so the
surface is measured once per module and every claim below comes off that single build.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from raven.core.middleware import MUTATING_METHODS
from raven.gateway.daemon import RavenFlowDaemon

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WEB = _ROOT / "web"
_MARKER = "\x00"
_HOST = re.compile(r"`\$\{protocol\}//\$\{location\.host\}([^`]*)`")


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


def _socket_path(template: str) -> str | None:
    """The path out of a `${protocol}//${location.host}...` template, with each `${...}` as a parameter.

    A placeholder glued to the end of a literal (`/aios/ws/agent${query}`) was a query string, not a
    segment; one that sits inside a segment the gate cannot name returns None and fails the build.
    """
    body = re.sub(r"\$\{[^}]*\}", _MARKER, template).partition("?")[0]
    parts = body.split("/")
    for index, part in enumerate(parts):
        if _MARKER not in part:
            continue
        if part == _MARKER:
            parts[index] = "{param}"
        elif part.endswith(_MARKER) and index == len(parts) - 1:
            parts[index] = part[: -len(_MARKER)]
        else:
            return None
    return "/".join(parts)


def _client_sockets() -> list[tuple[str, str]]:
    """`(file, path)` for every socket the SPA opens."""
    sources = [path for glob in ("**/*.ts", "**/*.tsx") for path in sorted((_WEB / "src").glob(glob))]
    found: list[tuple[str, str]] = []
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        templates = list(_HOST.finditer(text))
        opened = len(re.findall(r"new WebSocket\(", text))
        assert opened <= len(templates), (
            f"{path.relative_to(_ROOT)} opens {opened} sockets from {len(templates)} addressable URLs"
        )
        for template in templates:
            named = _socket_path(template.group(1))
            assert named is not None, f"{path.relative_to(_ROOT)} opens a socket at an unnameable path"
            found.append((str(path.relative_to(_ROOT)), named))
    return found


def _balanced_object(text: str, start: int) -> str:
    """The object literal starting at `start`, read with a balanced scan: its body holds nested braces."""
    depth, end = 0, start
    while end < len(text):
        depth += text[end] == "{"
        depth -= text[end] == "}"
        end += 1
        if depth == 0:
            return text[start:end]
    raise AssertionError("unbalanced object in vite.config.ts")


def _vite_proxy() -> list[tuple[str, bool]]:
    """`(prefix, upgrades_proxied)` for every dev proxy entry, in the order Vite matches them."""
    source = (_WEB / "vite.config.ts").read_text(encoding="utf-8")
    head = source.find("proxy:")
    assert head != -1, "the dev server must declare a proxy block"
    body = _balanced_object(source, source.index("{", head))
    entries: list[tuple[str, bool]] = []
    for match in re.finditer(r'"(/[^"]*)"\s*:', body):
        start = match.end()
        while body[start] in " \t\r\n":
            start += 1
        if body[start] == "{":
            value = _balanced_object(body, start)
        else:
            # A bare string entry runs to the next comma; reading further would let a later entry's
            # `ws: true` answer for this one.
            comma = body.find(",", start)
            value = body[start : len(body) if comma == -1 else comma]
        entries.append((match.group(1), bool(re.search(r"\bws:\s*true\b", value))))
    return entries


def _served_by(route_path: str, client_path: str) -> bool:
    route, client = route_path.split("/"), client_path.split("/")
    return len(route) == len(client) and all(
        behind == ahead or ahead == "{param}" or (behind.startswith("{") and behind.endswith("}"))
        for behind, ahead in zip(route, client, strict=True)
    )


class TestClientSockets:
    """The console opens three sockets. Two of the three claims below were false at the same time for
    the collaboration editor: the page never connected, and had it connected in dev, Vite would have
    answered the upgrade with a 426 because `/api` proxied HTTP only.
    """

    def test_the_console_opens_more_than_one_socket(self) -> None:
        # Guards the scan itself: a reader that matched nothing would pass every claim below.
        assert len({path for _, path in _client_sockets()}) >= 3

    def test_every_socket_the_console_opens_is_mounted_by_the_gateway(self, routes: list[tuple[str, str, str]]) -> None:
        sockets = [path for method, path, _ in routes if method == "WEBSOCKET"]
        for source, path in _client_sockets():
            assert any(_served_by(behind, path) for behind in sockets), (
                f"{source} opens {path}, which is mounted nowhere"
            )

    def test_every_socket_the_console_opens_is_proxied_for_upgrades_in_dev(self) -> None:
        entries = _vite_proxy()
        for source, path in _client_sockets():
            winners = [(prefix, ws) for prefix, ws in entries if path.startswith(prefix)]
            assert winners, f"{source} opens {path}, which the dev server does not proxy at all"
            prefix, upgrades = winners[0]
            assert upgrades, f"{source} opens {path}, matched by {prefix!r}, which proxies HTTP only"

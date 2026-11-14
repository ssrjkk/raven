from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

_ROUTER_PREFIX = re.compile('APIRouter\\(\\s*prefix="([^"]*)"')
_ROUTER_DECORATOR = re.compile('@router\\.(?:get|post|put|delete|patch|websocket)\\(\\s*"([^"]*)"')
_APP_DECORATOR = re.compile('@app\\.(?:get|post|put|delete|patch|websocket)\\(\\s*"([^"]*)"')
# A client names a URL either as a plain literal or as the tail of a template interpolation, and the
# two look nothing alike to a scanner that only accepts a quote before the slash: every URL the VS
# Code extension builds is of the second shape (`${this.urlBase}/api/raven`), which is how a probe of
# `/health` -- a path no server in this repo answers -- reached an installed extension.
_CLIENT_PATH = re.compile("[\"'`}](/(?:api|aios|ws|events|mcp)[A-Za-z0-9_./{}$?&=-]*)")

_PY_DIRS = ("raven", "aios")
# `extension/vscode/src`, not its `out/`: the gate reads the source the artifact is compiled from.
_CLIENT_DIRS = (("web", "src"), ("extension", "src"), ("extension", "vscode", "src"))
_CLIENT_SUFFIXES = (".ts", ".tsx", ".js")


def _served_paths() -> set[str]:
    paths: set[str] = set()
    files: list[pathlib.Path] = []
    for directory in _PY_DIRS:
        files.extend((ROOT / directory).rglob("*.py"))
    for path in files:
        prefix = ""
        text = path.read_text(encoding="utf-8", errors="ignore")
        found_prefixes = _ROUTER_PREFIX.findall(text)
        if len(found_prefixes) == 1:
            prefix = found_prefixes[0]
        for line in text.splitlines():
            prefix_match = _ROUTER_PREFIX.search(line)
            if prefix_match:
                prefix = prefix_match.group(1)
                continue
            route_match = _ROUTER_DECORATOR.search(line)
            if route_match:
                paths.add(prefix + route_match.group(1))
            app_match = _APP_DECORATOR.search(line)
            if app_match:
                paths.add(app_match.group(1))
    return paths


def _client_paths(dirs: tuple[tuple[str, ...], ...] = _CLIENT_DIRS) -> set[str]:
    paths: set[str] = set()
    for parts in dirs:
        for path in (ROOT / pathlib.Path(*parts)).rglob("*"):
            if path.suffix not in _CLIENT_SUFFIXES or not path.is_file():
                continue
            if "node_modules" in path.parts:
                continue
            paths.update(_CLIENT_PATH.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return paths


def _pruned(value: str) -> str:
    """Strip a query string and the variable part of a templated path.

    ``/api/monitors/{id}`` and ``/api/monitors/${id}`` both prune to ``/api/monitors`` so the two
    sides of the comparison are expressed the same way.
    """
    return value.split("?")[0].split("$")[0].split("{")[0].rstrip("/")


def _unreachable(used: set[str], served: set[str]) -> list[str]:
    served_pruned = {_pruned(path) for path in served}
    return sorted(path for path in sorted(used) if _pruned(path) not in served_pruned)


def test_the_sweep_reads_both_sides() -> None:
    assert len(_served_paths()) > 250
    assert len(_client_paths()) > 100


def test_the_vscode_extension_is_part_of_the_sweep() -> None:
    """It shipped a health probe of `/health` -- a path no server here answers -- for as long as the
    directory it lives in was not swept. A pattern that finds nothing in a client is blind, not clean.

    The second line is the one that matters: a directory read only when a test names it explicitly is
    not part of the sweep at all, so the check has to go through the default set of clients.
    """
    used = _client_paths((("extension", "vscode", "src"),))
    assert used, "no URL found in extension/vscode/src"
    missing = used - _client_paths()
    assert missing == set(), f"the sweep skips these extension/vscode URLs: {sorted(missing)}"


def test_the_scanner_reads_a_path_out_of_a_template_literal() -> None:
    assert _CLIENT_PATH.findall("fetch(`${base}/api/raven`") == ["/api/raven"]
    assert _CLIENT_PATH.findall("new WebSocket(`wss://${host}/ws`)") == ["/ws"]
    assert _CLIENT_PATH.findall("fetch(`${this.urlBase}/ws/agent${query}`)") == ["/ws/agent${query}"]
    # a relative module import shares the prefix but is not a URL, and must stay out of the comparison
    assert _CLIENT_PATH.findall('import { api } from "../api/client";') == []
    assert _CLIENT_PATH.findall("host = 'api.example.com'") == []


def test_the_comparison_reports_a_path_the_backend_never_mounted() -> None:
    missing = _unreachable({"/api/admin/never-mounted"}, {"/api/admin/config"})
    assert missing == ["/api/admin/never-mounted"]


def test_every_path_the_clients_call_is_served_by_the_backend() -> None:
    missing = _unreachable(_client_paths(), _served_paths())
    assert missing == []

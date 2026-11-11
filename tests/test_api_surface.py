from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

_ROUTER_PREFIX = re.compile('APIRouter\\(\\s*prefix="([^"]*)"')
_ROUTER_DECORATOR = re.compile('@router\\.(?:get|post|put|delete|patch|websocket)\\(\\s*"([^"]*)"')
_APP_DECORATOR = re.compile('@app\\.(?:get|post|put|delete|patch|websocket)\\(\\s*"([^"]*)"')
_CLIENT_PATH = re.compile("[\"`'](/(?:api|aios|ws|events|mcp)[A-Za-z0-9_./{}$?&=-]*)")

_PY_DIRS = ("raven", "aios")
_CLIENT_DIRS = (("web", "src"), ("extension", "src"))
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


def _client_paths() -> set[str]:
    paths: set[str] = set()
    for parts in _CLIENT_DIRS:
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


def test_the_comparison_reports_a_path_the_backend_never_mounted() -> None:
    missing = _unreachable({"/api/admin/never-mounted"}, {"/api/admin/config"})
    assert missing == ["/api/admin/never-mounted"]


def test_every_path_the_clients_call_is_served_by_the_backend() -> None:
    missing = _unreachable(_client_paths(), _served_paths())
    assert missing == []

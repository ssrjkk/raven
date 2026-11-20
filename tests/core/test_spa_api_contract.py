"""Every payload the console's status surfaces are tested with must be the server's own answer.

`web/e2e/fixtures/health.ts` exists because a hand-typed `/api/health` stub — a `checks` array the server has
never emitted — kept the dashboard spec green while the shipped page threw `p.checks.map is not a function`
into its error boundary. The same pattern was still sitting on the other four payloads the console reads, in
three e2e specs and `web/src/pages/Dashboard.test.tsx`, until `scripts/gen_api_fixtures.py` started asking the
routers for them. What was inventable there was invented: `version: "0.4.8"` and `"0.4.0"` where the route
answered `"1.0.0"` (the routes themselves were reporting a version the product never had), metric keys named
`requests_total` and `avg_latency_ms` where `metrics.snapshot()` prefixes everything `raven_<name>_…`, and a
monitor list whose `effective_interval`, `group` and per-row `version` the SPA never declared because nobody
had read them from the server.

These tests hold the links the generator cannot: the committed fixture still equals the routers' answer, each
payload is typed by the SPA's own declaration, the two routes that describe the same gateway agree about it,
and no file in the web tree answers these routes with a payload typed by hand again.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
from types import ModuleType
from typing import Any, cast

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "e2e" / "fixtures" / "api.ts"
TYPES = REPO / "web" / "src" / "api" / "types.ts"
WEB = REPO / "web"

# The route, the client method that calls it, and the name its answer is exported as in the fixture. The
# method is `None` for `/api/monitor/list`: `api.monitors()` resolves to the envelope's `items`, so a stub of
# that method is not this payload and only the route is scanned for it.
ROUTES: dict[str, tuple[str | None, str]] = {
    "/api/status": ("status", "status"),
    "/api/admin/system/status": ("systemStatus", "systemStatus"),
    "/api/metrics": ("metrics", "metrics"),
    "/api/monitor/list": (None, "monitorList"),
}

_ROUTES = "|".join(re.escape(route) for route in ROUTES)
_METHODS = "|".join(method for method, _export in ROUTES.values() if method)

_EXPORT = re.compile(r"const (\w+)Answer = (\{.*?\n\});\nexport const (\w+): (\w+) = \3Answer;", re.DOTALL)
"""One emitted payload: the JSON the route answered, the name it is exported under, and the SPA type it is
annotated with. The annotation is the link this file cannot re-check by parsing — it is enforced by
`tsc --noEmit -p tsconfig.e2e.json` failing to compile a payload the declaration rejects."""

_ANSWER = re.compile(
    rf'"(?:{_ROUTES})"\s*:|\b(?:{_METHODS})\s*:\s*vi\.fn\(\)\.mockResolvedValue\(',
    re.MULTILINE,
)
"""A file that hands the console one of these payloads: a stub keyed by the route, or a stub of the client
method that calls it. The method form is what a vitest page test uses, and it is how the unit test kept the
invented `requests_total` metrics alive while the page was claimed to be covered."""

_ANSWERED_WITH = re.compile(
    rf'"(?:{_ROUTES})"\s*:\s*([A-Za-z_$][\w$]*|\{{)'
    rf"|\b(?:{_METHODS})\s*:\s*vi\.fn\(\)\.mockResolvedValue\(\s*([A-Za-z_$][\w$]*|\{{)\s*\)",
)
"""What each of those stubs resolves to — `{` for a payload written into the file, which is what fails here."""

_FIXTURE_IMPORT = re.compile(r'from\s+"[^"]*fixtures/api"')


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_api_fixtures", REPO / "scripts" / "gen_api_fixtures.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def emitted(generator: ModuleType) -> str:
    """One run of the routers, shared by every claim below: building a gateway costs about twenty seconds."""
    return cast("str", generator.render())


@pytest.fixture(scope="module")
def answers(emitted: str) -> dict[str, tuple[dict[str, Any], str]]:
    """The payload each route answered, with the SPA type it was annotated as."""
    return {name: (json.loads(body), kind) for _var, body, name, kind in _EXPORT.findall(emitted)}


def test_the_committed_fixture_is_what_the_routes_answer(emitted: str) -> None:
    """Byte for byte, so a field renamed on either side fails here instead of in a browser."""
    assert FIXTURE.is_file(), "web/e2e/fixtures/api.ts is missing — run python scripts/gen_api_fixtures.py --write"
    assert FIXTURE.read_text(encoding="utf-8") == emitted, (
        "web/e2e/fixtures/api.ts no longer matches what the status routes answer — "
        "run python scripts/gen_api_fixtures.py --write"
    )


def test_the_render_answers_for_itself_and_not_for_the_session(generator: ModuleType) -> None:
    """The gate above runs in a process holding thousands of tests' metrics; the fixture does not.

    `/api/metrics` reports what the process has measured, so a render that inherited the session's
    counters emitted `db_query` and `llm_complete` families no fresh process ever produced, and the
    byte-for-byte comparison failed only inside the full run — the committed file was right and the
    order was wrong. `_state_as_found` has to start the registries empty and hand the session back
    exactly what it found.
    """
    from raven.core.metrics import metrics

    found = (
        dict(metrics._counters),
        {key: list(value) for key, value in metrics._latencies.items()},
        dict(metrics._errors),
    )
    try:
        metrics.inc("llm_complete", {"provider": "openai", "model": "gpt-4o", "status": "ok"})
        metrics.observe("db_query", 0.0011, {"operation": "get_or_create_session"})
        polluted = {key for key in metrics.snapshot() if "db_query" in key or "llm_complete" in key}
        assert len(polluted) >= 5, polluted

        with generator._state_as_found():
            metrics.inc("messages_sent", {"channel": "webchat"})
            rendered = set(metrics.snapshot())
        warmed = {"raven_messages_sent{channel=webchat}_total"}
        assert rendered == warmed, f"the render carried {sorted(rendered - warmed)} that only the session recorded"

        after = set(metrics.snapshot())
        assert polluted <= after, "the render swallowed the session's own measurements instead of restoring them"
    finally:
        metrics._counters, metrics._latencies, metrics._errors = found


def test_every_payload_is_typed_by_the_spas_own_declaration(
    answers: dict[str, tuple[dict[str, Any], str]],
) -> None:
    """A generated file nothing types is a generated file that can say anything."""
    declared = set(re.findall(r"^export interface (\w+)", TYPES.read_text(encoding="utf-8"), re.MULTILINE))
    expected = {export for _method, export in ROUTES.values()}
    assert set(answers) == expected, f"the fixture exports {sorted(answers)}, the routes answer {sorted(expected)}"
    for name, (_payload, kind) in answers.items():
        assert kind in declared, f"{name} is annotated {kind}, which web/src/api/types.ts does not declare"


def test_the_two_routes_that_describe_one_gateway_agree(answers: dict[str, tuple[dict[str, Any], str]]) -> None:
    """A dashboard card takes `channels` from one route and falls back to the other, so the pair is one claim.

    Hand-typed stubs are where that agreement is invented rather than measured: the payloads this file
    replaced said 3 channels and 2 agents next to `["webchat"]` and no agents at all, and nothing could see it.
    """
    status, _kind = answers["status"]
    system, _system_kind = answers["systemStatus"]
    assert system["channels"] == len(status["channels"]), f"{system['channels']} against {status['channels']}"
    assert system["agents"] == len(status["agents"]), f"{system['agents']} against {len(status['agents'])}"
    assert system["version"] == status["version"], f"{system['version']} against {status['version']}"


def test_the_version_the_status_routes_answer_is_the_products_own(
    answers: dict[str, tuple[dict[str, Any], str]],
) -> None:
    """The console puts this on screen as the version the operator is running.

    `raven/core/version.py` resolves it from `pyproject.toml`; both status routes used to answer `"1.0.0"`
    while the package was `0.4.8`, because the version-consistency gate listed every declaring file except
    those two answers.
    """
    from raven.core.version import __version__

    for name in ("status", "systemStatus"):
        payload, _kind = answers[name]
        assert payload["version"] == __version__, f"{name} answers {payload['version']!r}, running is {__version__}"


def test_every_status_the_web_tree_answers_is_a_name_from_the_fixture() -> None:
    """The scan that catches the next hand-typed payload, in the unit tests as well as the specs."""
    exports = set(re.findall(r"export const (\w+)", FIXTURE.read_text(encoding="utf-8")))
    assert exports, f"{FIXTURE} exports nothing — regenerate it with python scripts/gen_api_fixtures.py --write"

    authors = sorted(
        path
        for directory in (WEB / "src", WEB / "e2e")
        for path in [*directory.rglob("*.ts"), *directory.rglob("*.tsx")]
        if _ANSWER.search(path.read_text(encoding="utf-8"))
    )
    assert len(authors) >= 4, (
        f"only {authors} answers these routes in the web tree — the tree gained a way to serve the payload "
        "without this gate noticing, or the stubs were renamed and are no longer found"
    )
    for path in authors:
        source = path.read_text(encoding="utf-8")
        assert _FIXTURE_IMPORT.search(source), (
            f"{path.relative_to(REPO)} answers a status route without importing the generated payload — "
            "type it by hand and the page can crash on the server's real shape while you stay green"
        )
        names = {name for pairs in _ANSWERED_WITH.findall(source) for name in pairs if name}
        assert names and names <= exports, (
            f"{path.relative_to(REPO)} answers these routes with {sorted(names) or 'a literal'}; "
            f"the routes' payloads offer {sorted(exports)}"
        )

"""The SPA's copy of `/api/health` must stay the server's own answer.

Measured on a live gateway on 2026-11-18: `Dashboard.tsx` crashed into its error boundary
(`TypeError: p.checks.map is not a function`). `HealthRegistry.check_all()` answers `checks` as a mapping of
name to result, while `web/src/api/types.ts` declared an array of `{name, ok, latency_ms, critical}` and
`web/e2e/dashboard.spec.ts` stubbed that invented array — so the specs stayed green over a page that had never
rendered. The hole was that the test payload was typed by hand: nothing connected it to the route.

`scripts/gen_health_fixture.py` closes it by asking the route itself, and the emitted module is annotated with
`HealthData`, so the SPA's declaration and the server's answer have to agree for the e2e tree to compile.
These tests hold the remaining links: the committed fixture still equals the route, and the spec still reads
the fixture rather than a literal. A check added to `HealthMonitor.register_checks()` reaches the fixture
through the same path, so it shows up as drift here too.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
from types import ModuleType

import pytest

from raven.core.health import health

REPO = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO / "web" / "e2e" / "fixtures" / "health.ts"
SPEC = REPO / "web" / "e2e" / "dashboard.spec.ts"
WEB = REPO / "web"

_ANSWER_HEALTH = re.compile(r'"/api/health"\s*:|\bhealth\s*:\s*vi\.fn\(', re.MULTILINE)
"""A file that hands the SPA the answer of the health route: a stub keyed by the path, or a stub of the client."""

_FIXTURE_IMPORT = re.compile(r'from\s+"[^"]*fixtures/health"')

_ANSWERED_WITH = re.compile(
    r'"/api/health"\s*:\s*([A-Za-z_$][\w$]*)|health\s*:\s*vi\.fn\(\)\.mockResolvedValue\(\s*([A-Za-z_$][\w$]*)\s*\)'
)
"""The identifier each of those stubs resolves — empty for a literal written into the file."""


@pytest.fixture(scope="module", autouse=True)
def _registry_left_as_found():
    """The fixture is emitted through production's wiring — `HealthMonitor` and the route both address the
    module-level `health` singleton — so this file registers into it and hands it back."""
    before = dict(health._checks)
    yield
    health._checks.clear()
    health._checks.update(before)


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_health_fixture", REPO / "scripts" / "gen_health_fixture.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixture_is_what_the_route_answers(generator: ModuleType) -> None:
    """Byte for byte, so a field renamed on either side fails here instead of in a browser."""
    assert FIXTURE.is_file(), "web/e2e/fixtures/health.ts is missing — run python scripts/gen_health_fixture.py --write"
    assert FIXTURE.read_text(encoding="utf-8") == generator.render(), (
        "web/e2e/fixtures/health.ts no longer matches what /api/health answers — "
        "run python scripts/gen_health_fixture.py --write"
    )


def test_the_spec_uses_the_fixture_instead_of_typing_one() -> None:
    """A fixture nothing imports guards nothing."""
    source = SPEC.read_text(encoding="utf-8")
    assert re.search(r'from "\./fixtures/health"', source), "dashboard.spec.ts stopped importing the generated fixture"
    bodies = [body.strip() for body in re.findall(r'"/api/health":\s*([^,}\n]+)', source)]
    assert bodies and set(bodies) <= {"healthOk", "healthDegraded"}, (
        f"dashboard.spec.ts answers /api/health with {bodies} — a payload typed by hand is exactly how the "
        "invented `checks` array stayed green over a page that crashed; use the generated fixture"
    )


def test_every_health_the_web_tree_answers_is_a_name_from_the_fixture() -> None:
    """The scan that would have caught the unit test, not only the spec.

    The crash this file exists for reached production with `web/src/pages/Dashboard.test.tsx` mocking the same
    invented array, so a gate aimed at one file leaves the other half of the tree free to type its own payload.
    This asks the source surface the project's own lint covers (`eslint src e2e`) who hands the SPA an
    `/api/health` answer — a route stub keyed by the path, or a stub of the client's `health()` — and requires
    each of them to import the generated module and name one of its exports. An inline literal names nothing,
    so it fails here; a check added to `register_checks()` reaches the fixture and every caller through
    `gen_health_fixture.py`, so it never needs a new hand-typed copy.
    """
    fixture_exports = set(re.findall(r"export const (\w+)", FIXTURE.read_text(encoding="utf-8")))
    assert fixture_exports, (
        f"{FIXTURE} exports nothing — regenerate it with python scripts/gen_health_fixture.py --write"
    )

    authors = sorted(
        path
        for directory in (WEB / "src", WEB / "e2e")
        for path in [*directory.rglob("*.ts"), *directory.rglob("*.tsx")]
        if _ANSWER_HEALTH.search(path.read_text(encoding="utf-8"))
    )
    assert len(authors) >= 2, (
        f"only {authors} answers /api/health in the web tree — the tree gained a way to serve the payload "
        "without this gate noticing, or the stubs were renamed and are no longer found"
    )
    for path in authors:
        source = path.read_text(encoding="utf-8")
        assert _FIXTURE_IMPORT.search(source), (
            f"{path.relative_to(REPO)} answers /api/health without importing the generated payload — "
            "type it by hand and the page can crash on the server's real shape while you stay green"
        )
        names = {name for pairs in _ANSWERED_WITH.findall(source) for name in pairs if name}
        assert names and names <= fixture_exports, (
            f"{path.relative_to(REPO)} answers /api/health with {sorted(names) or 'a literal'}; "
            f"the route's payload offers {sorted(fixture_exports)}"
        )

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "web" / "src"

_SPECIFIER = re.compile(r"""(?:from|import)\s*\(?\s*["'`]([^"'`]+)["'`]""")
_SUFFIXES = (".ts", ".tsx")


def _modules() -> list[pathlib.Path]:
    return sorted(p for p in SRC.rglob("*") if p.is_file() and p.suffix in _SUFFIXES)


def _resolve(spec: str, origin: pathlib.Path) -> pathlib.Path | None:
    if not spec.startswith("."):
        return None
    base = (origin.parent / spec).resolve()
    for candidate in (
        base,
        pathlib.Path(str(base) + ".ts"),
        pathlib.Path(str(base) + ".tsx"),
        base / "index.ts",
        base / "index.tsx",
    ):
        if candidate.is_file():
            return candidate
    return None


def _deps_of(file: pathlib.Path) -> set[pathlib.Path]:
    text = file.read_text(encoding="utf-8", errors="ignore")
    found: set[pathlib.Path] = set()
    for spec in set(_SPECIFIER.findall(text)):
        target = _resolve(spec, file)
        if target is not None:
            found.add(target)
    return found


def _closure(entries: list[pathlib.Path], deps_of=_deps_of) -> set[pathlib.Path]:
    seen: set[pathlib.Path] = set()
    stack = list(entries)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(n for n in deps_of(current) if n not in seen)
    return seen


def _is_exempt(file: pathlib.Path) -> bool:
    rel = file.relative_to(SRC).as_posix()
    # A test file is the root of its own graph; the helpers under src/test are loaded by
    # vitest.config.ts; a .d.ts file carries no runtime at all.
    return bool(re.search(r"\.test\.tsx?$", rel)) or rel.startswith("test/") or rel.endswith(".d.ts")


def test_the_walk_finds_a_real_graph() -> None:
    reachable = _closure([SRC / "main.tsx"])
    assert len(reachable) > 60, len(reachable)
    assert len(_modules()) > 90, len(_modules())


def test_the_bundle_ships_no_module_the_entry_point_cannot_reach() -> None:
    reachable = _closure([SRC / "main.tsx"])
    orphans = sorted(p.relative_to(SRC).as_posix() for p in _modules() if p not in reachable and not _is_exempt(p))
    assert orphans == []


def test_the_entry_point_loads_the_browser_tracer_it_ships() -> None:
    reachable = _closure([SRC / "main.tsx"])
    assert SRC / "instrumentation.ts" in reachable


def test_the_closure_reports_a_module_nothing_imports() -> None:
    graph = {
        SRC / "entry.ts": {SRC / "used.ts"},
        SRC / "used.ts": set(),
    }
    reached = _closure([SRC / "entry.ts"], lambda file: graph.get(file, set()))
    assert reached == {SRC / "entry.ts", SRC / "used.ts"}
    assert SRC / "orphan.ts" not in reached

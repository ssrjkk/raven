"""The Docker build context has to contain what pyproject tells hatchling to put in the wheel.

`python -m build` runs inside the image from the copied context only, so a path pyproject names and
the Dockerfile never copies is not a warning: hatchling raises `Forced include not found` and the
image cannot be built at all. That is how the wheel-builder stage broke — `policy/tools.json` became
a force-include and the stage kept copying just the three packages.

The same file decides which interpreter every customer runs, and the suite decides which interpreters
get tested; nothing linked the two, so dependabot moved the image onto a Python no CI job had ever
imported the package under.

The `web-builder` stage has the same boundary: it copies `web/` and `tsconfig.base.json` alone, so a
relative import that climbs out of `web/` names a module the image does not have and `tsc -b` fails
the build — which the frontend CI job cannot see, because it runs in the full checkout.
"""

from __future__ import annotations

import pathlib
import re
import tomllib
from typing import Final

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE: Final = ROOT / "Dockerfile"
CI_WORKFLOW: Final = ROOT / ".github/workflows/ci.yml"


def wheel_inputs() -> list[str]:
    """Every repository path the wheel target pulls in, as pyproject declares it."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]
    inputs = list(wheel.get("packages", []))
    inputs.extend(source for source in wheel.get("force-include", {}))
    return sorted(set(inputs))


def staged_copies(stage: str = "wheel-builder") -> list[str]:
    """Sources one stage copies into its working directory.

    Only the stage that builds an artifact matters: a `COPY` in the runtime stage cannot put a file
    inside a wheel that was already built by the time the runtime stage runs.
    """
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    current: str | None = None
    copied: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FROM "):
            current = stripped.split()[-1]
            continue
        if current == stage and stripped.startswith("COPY "):
            args = [part for part in stripped.split()[1:] if not part.startswith("--")]
            copied.extend(args[:-1])
    return copied


def unstaged(inputs: list[str], copied: list[str]) -> list[str]:
    """Inputs no copied source covers: an exact match, or a directory copied with a trailing slash."""
    missing: list[str] = []
    for required in inputs:
        norm = required.rstrip("/")
        covered = any(src.rstrip("/") == norm or (src.endswith("/") and (norm + "/").startswith(src)) for src in copied)
        if not covered:
            missing.append(required)
    return missing


def image_bases() -> list[str]:
    """The interpreter tag of every `python:` image the Dockerfile builds on, in source order."""
    return re.findall(r"^FROM python:(\S+)", DOCKERFILE.read_text(encoding="utf-8"), re.MULTILINE)


def matrix_interpreters() -> list[str]:
    """The Python versions the `check` job runs the suite under, read off the matrix it declares."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    matrix = next((raw for raw in text.splitlines() if raw.strip().startswith("python-version: [")), "")
    found = re.findall(r"""['"](\d+\.\d+)['"]""", matrix)
    assert found, f"ci.yml declares no test matrix this gate can read: {matrix!r}"
    return found


def untested(bases: list[str], tested: list[str]) -> list[str]:
    """Bases whose `major.minor` no CI job tests; a patch tag still names the stream it runs."""
    offenders: list[str] = []
    for base in bases:
        stream = re.match(r"\d+\.\d+", base)
        assert stream, f"{base!r} is not a Python version"
        if stream.group() not in tested:
            offenders.append(base)
    return offenders


def test_everything_the_wheel_target_pulls_in_is_in_the_build_context() -> None:
    inputs = wheel_inputs()
    for required in inputs:
        assert (ROOT / required).exists(), f"pyproject names {required}, which the repository does not have"
    missing = unstaged(inputs, staged_copies())
    assert not missing, f"Dockerfile wheel-builder stage does not copy: {missing}"


def test_the_detector_reports_a_path_the_dockerfile_stops_copying() -> None:
    """The gate must be able to fail: dropping one COPY has to name that path."""
    inputs = wheel_inputs()
    copied = staged_copies()
    for required in inputs:
        covering = [src for src in copied if not unstaged([required], [src])]
        assert covering, f"{required} is staged by no COPY this test can drop"
        misses = unstaged(inputs, [src for src in copied if src not in covering])
        assert required in misses, f"dropping {covering} did not make {required} a finding"


def test_the_image_runs_an_interpreter_ci_tests() -> None:
    """An image built on a stream CI never imports the package under ships untested code to customers.

    The base image is the one version here a bot can move on its own, so both tables are read from
    the files that own them instead of repeated in a test: the matrix is the contract, the Dockerfile
    has to name a stream inside it.
    """
    bases = image_bases()
    assert bases, "the Dockerfile builds on no python image"
    offenders = untested(bases, matrix_interpreters())
    assert not offenders, f"image bases no CI job tests: {offenders}"


def test_the_interpreter_detector_reports_a_base_ci_never_tests() -> None:
    """The gate must be able to fail: a base outside the matrix has to come back named by version."""
    tested = matrix_interpreters()
    assert len(tested) >= 2, f"the matrix parse returned {tested}"
    assert untested(["3.99-slim"], tested) == ["3.99-slim"]
    assert not untested(tested, tested)
    assert not untested([f"{tested[0]}.4-slim"], tested), "a patch of a tested stream is that stream"


WEB_SRC: Final = ROOT / "web" / "src"
_RELATIVE_IMPORT = re.compile(r"""(?:\bfrom|\bimport)\s*\(?\s*['"](\.[^'"]+)['"]""")
_EXTENSIONS: Final = (".ts", ".tsx", ".json")


def resolve_import(source: pathlib.Path, specifier: str) -> pathlib.Path | None:
    """The file a relative specifier names, the way `tsc -b` and Vite resolve it."""
    base = source.parent / specifier
    for candidate in (base, *(base.with_suffix(ext) for ext in _EXTENSIONS), base / "index.ts", base / "index.tsx"):
        if candidate.is_file():
            return candidate.resolve()
    return None


def web_imports() -> list[tuple[str, str, str | None]]:
    """(importing file, specifier, target) for every relative import under `web/src`."""
    found: list[tuple[str, str, str | None]] = []
    for source in sorted(WEB_SRC.rglob("*")):
        if source.suffix not in {".ts", ".tsx"}:
            continue
        rel = source.relative_to(ROOT).as_posix()
        for specifier in _RELATIVE_IMPORT.findall(source.read_text(encoding="utf-8")):
            target = resolve_import(source, specifier)
            if target is None:
                found.append((rel, specifier, None))
            elif target.is_relative_to(ROOT):
                found.append((rel, specifier, target.relative_to(ROOT).as_posix()))
            else:
                found.append((rel, specifier, str(target)))
    return found


def uncovered_web_imports(copied: list[str]) -> list[str]:
    offenders: list[str] = []
    for rel, specifier, target in web_imports():
        if target is None:
            offenders.append(f"{rel} -> {specifier} (resolves to no file)")
        elif unstaged([target], copied):
            offenders.append(f"{rel} -> {specifier} ({target})")
    return offenders


def test_every_web_import_is_inside_the_web_build_context() -> None:
    """`npm run build` runs `tsc -b` over all of `web/src`, tests included, from the copied tree alone.

    A specifier that climbs out of `web/` is therefore not a style question: the module is absent in
    the image, TS2307 fails the build, and no image is published. The frontend CI job cannot see it,
    because that one runs in the full checkout where the file is still there.
    """
    imports = web_imports()
    assert len(imports) > 200, f"the web import scan covered only {len(imports)} imports - it is vacuous"
    offenders = uncovered_web_imports(staged_copies("web-builder"))
    assert not offenders, f"web imports the image build context does not contain: {offenders}"


def test_the_web_context_detector_reports_an_import_outside_the_copied_tree() -> None:
    """The gate must be able to fail, on the shape that actually broke the image."""
    probe = WEB_SRC / "lib" / "__docker_context_probe__.ts"
    probe.write_text('import "../../../pyproject.toml";\n', encoding="utf-8")
    try:
        offenders = uncovered_web_imports(staged_copies("web-builder"))
        assert any(probe.name in row and "pyproject.toml" in row for row in offenders), offenders
    finally:
        probe.unlink()
    assert not uncovered_web_imports(staged_copies("web-builder"))


def test_dropping_the_web_copy_makes_the_imports_findings() -> None:
    copied = [src for src in staged_copies("web-builder") if src.rstrip("/") != "web"]
    assert copied, "the web-builder stage parses to no COPY at all"
    assert uncovered_web_imports(copied), "dropping `COPY web/ ./` named not one import"

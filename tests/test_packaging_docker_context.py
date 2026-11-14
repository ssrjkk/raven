"""The Docker build context has to contain what pyproject tells hatchling to put in the wheel.

`python -m build` runs inside the image from the copied context only, so a path pyproject names and
the Dockerfile never copies is not a warning: hatchling raises `Forced include not found` and the
image cannot be built at all. That is how the wheel-builder stage broke — `policy/tools.json` became
a force-include and the stage kept copying just the three packages.

The same file decides which interpreter every customer runs, and the suite decides which interpreters
get tested; nothing linked the two, so dependabot moved the image onto a Python no CI job had ever
imported the package under.
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


def staged_copies() -> list[str]:
    """Sources the `wheel-builder` stage copies into `/build`.

    Only that stage matters: a `COPY` in the runtime stage cannot put a file inside a wheel that was
    already built by the time the runtime stage runs.
    """
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    stage: str | None = None
    copied: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("FROM "):
            stage = stripped.split()[-1]
            continue
        if stage == "wheel-builder" and stripped.startswith("COPY "):
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

"""The Docker build context has to contain what pyproject tells hatchling to put in the wheel.

`python -m build` runs inside the image from the copied context only, so a path pyproject names and
the Dockerfile never copies is not a warning: hatchling raises `Forced include not found` and the
image cannot be built at all. That is how the wheel-builder stage broke — `policy/tools.json` became
a force-include and the stage kept copying just the three packages.
"""

from __future__ import annotations

import pathlib
import tomllib
from typing import Final

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE: Final = ROOT / "Dockerfile"


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

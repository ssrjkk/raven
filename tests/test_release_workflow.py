"""The Windows release path: checksum it, verify the checksum, attest it, document how to check it.

Each rule here has a failure mode behind it. A release with no checksum is a download you cannot
integrity-check; a checksum verified after the upload means a corrupted artifact still ships; an
`|| true` on the verification makes the whole control decorative; and an attestation nobody can
find in the docs is provenance that only the author ever uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "exe-build.yml"
DOCS = ROOT / "docs" / "getting-started.md"

EXE_ARTIFACT = "packaging/dist/Raven.exe"
SUM_ARTIFACT = "packaging/dist/Raven.exe.sha256"


def _jobs() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict) and isinstance(loaded.get("jobs"), dict)
    return {str(key): value for key, value in loaded["jobs"].items()}


def _steps(job: str) -> list[dict[str, Any]]:
    steps = _jobs()[job]["steps"]
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _haystack(step: dict[str, Any]) -> str:
    return " ".join(str(step.get(key) or "") for key in ("name", "uses", "run"))


def _find(job: str, needle: str) -> dict[str, Any]:
    matches = [s for s in _steps(job) if needle in _haystack(s)]
    assert matches, f"no step in {job} matching {needle!r}"
    return matches[0]


def _index(job: str, needle: str) -> int:
    return next(i for i, s in enumerate(_steps(job)) if needle in _haystack(s))


def test_the_build_writes_a_sha256_for_the_exe() -> None:
    step = _find("build-exe", "SHA-256")
    script = step["run"]
    assert "Get-FileHash" in script and "SHA256" in script
    assert "Raven.exe.sha256" in script
    assert "$env:GITHUB_STEP_SUMMARY" in script, "the digest should be visible on the run page"


def test_the_artifact_carries_both_the_binary_and_its_checksum() -> None:
    upload = _find("build-exe", "actions/upload-artifact")
    paths = str(upload["with"]["path"])
    assert EXE_ARTIFACT in paths and SUM_ARTIFACT in paths


def test_the_checksum_is_verified_before_anything_is_published() -> None:
    verify = _index("upload-release", "Verify the checksum")
    publish = _index("upload-release", "softprops/action-gh-release")
    assert verify < publish, "a corrupted artifact must never reach the release"
    command = _steps("upload-release")[verify]["run"]
    assert "sha256sum --check" in command
    assert "||" not in command and "true" not in command, "a gate that cannot fail is not a gate"


def test_the_release_artifacts_are_attested() -> None:
    attest = _find("upload-release", "actions/attest-build-provenance")
    assert attest["uses"].endswith("@v2"), "pin the action to a major tag, not @main"
    subjects = str(attest["with"]["subject-path"])
    assert EXE_ARTIFACT in subjects and SUM_ARTIFACT in subjects


def test_the_attest_job_has_only_the_permissions_it_needs() -> None:
    permissions = _jobs()["upload-release"].get("permissions") or {}
    assert permissions == {"contents": "write", "id-token": "write", "attestations": "write"}


def test_the_release_attaches_both_files() -> None:
    release = _find("upload-release", "softprops/action-gh-release")
    files = str(release["with"]["files"])
    assert EXE_ARTIFACT in files and SUM_ARTIFACT in files


def test_the_docs_tell_a_user_how_to_check_the_download() -> None:
    text = DOCS.read_text(encoding="utf-8")
    assert "sha256sum --check Raven.exe.sha256" in text
    assert "certutil -hashfile Raven.exe SHA256" in text, "the Windows-native way has to be named too"
    assert "gh attestation verify" in text
    assert "releases/latest/download/Raven.exe.sha256" in text
    # provenance is not a safety verdict; the doc must not imply one
    assert "not that it is safe to run" in text

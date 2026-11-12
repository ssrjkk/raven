"""Docs must not claim what the code does not do: commands it lacks, checks it never runs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = [
    ROOT / "README.md",
    *sorted((ROOT / "docs").glob("*.md")),
    *sorted((ROOT / "docs" / "channels").glob("*.md")),
    *sorted((ROOT / "docs" / "concepts").glob("*.md")),
    *sorted((ROOT / "docs" / "security").glob("*.md")),
]

# Only backticked invocations and code-block lines count — prose ("the raven install root") is ignored
INLINE_RE = re.compile(r"`(?:python -m )?raven ([a-z][a-z0-9_-]*)")
LINE_RE = re.compile(r"^\s*(?:\$ |> )?(?:python -m )?raven ([a-z][a-z0-9_-]*)", re.MULTILINE)


def _documented_commands(text: str) -> set[str]:
    return set(INLINE_RE.findall(text)) | set(LINE_RE.findall(text))


def _cli_commands() -> set[str]:
    from raven.cli.main import cli

    return set(cli.commands)


def test_documented_cli_commands_exist() -> None:
    available = _cli_commands()
    missing: dict[str, list[str]] = {}
    for path in DOC_FILES:
        if not path.is_file():
            continue
        for command in _documented_commands(path.read_text(encoding="utf-8")):
            if command not in available:
                missing.setdefault(command, []).append(path.name)
    assert missing == {}, f"Docs reference unknown `raven` commands: {missing}"


def test_docs_cover_core_commands() -> None:
    documented: set[str] = set()
    for path in DOC_FILES:
        if path.is_file():
            documented |= _documented_commands(path.read_text(encoding="utf-8"))
    core = {"start", "stop", "status", "doctor", "onboard", "init", "service", "tui", "security"}
    assert core <= documented, f"Core commands undocumented: {sorted(core - documented)}"


@pytest.mark.parametrize("name", ["start", "stop", "status", "doctor", "onboard", "init", "service", "tui"])
def test_core_commands_still_registered(name: str) -> None:
    assert name in _cli_commands()


def test_security_md_counts_the_checks_the_audit_actually_runs() -> None:
    """SECURITY.md advertises `raven security audit` by its check count, and the count it carried (23)
    was one more than the list the code builds (22) — a reader looking for the missing check would find
    no such control. The number is read out of the sentence and compared with what is produced."""
    from raven.core.security.security_audit import SecurityAudit

    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    match = re.search(r"(\d+) стандартных", text)
    assert match, "SECURITY.md no longer states the standard check count, so this guard has no anchor"
    # The `--deep` count is not gated here: building that list probes Docker and the dependency tree,
    # measured at 16.56 s, which is a CI job rather than a unit test.
    assert int(match.group(1)) == len(SecurityAudit().run_all(deep=False))

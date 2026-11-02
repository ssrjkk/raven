"""The local gate must fail on exactly what CI fails on.

CI's `frontend` job runs five commands; the local stage ran three of them (npm ci, tsc, build), so a
lint violation added while translating the SPA strings merged green at home and red in CI - an
`simple-import-sort/imports` error in `web/src/hooks/command-keywords.test.ts` that nothing local
would have caught. This guard reads the job's own `run:` steps and requires each to be present in
`scripts/check_all.py`, so the two cannot drift apart again without failing the build.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
GATE = (ROOT / "scripts" / "check_all.py").read_text(encoding="utf-8")


def ci_frontend_commands() -> list[str]:
    workflow = yaml.safe_load(CI_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["frontend"]["steps"]
    return [str(step["run"]).strip() for step in steps if isinstance(step, dict) and "run" in step]


def _argv_literal(command: str) -> str:
    return "[" + ", ".join(f'"{part}"' for part in command.split()) + "]"


def test_the_ci_frontend_job_runs_the_steps_this_guard_reads() -> None:
    commands = ci_frontend_commands()
    assert commands == [
        "npm ci",
        "npx tsc --noEmit",
        "npx eslint src",
        "npm test -- --run",
        "npm run build",
    ], commands


def test_the_local_frontend_stage_checks_everything_ci_checks() -> None:
    missing = [command for command in ci_frontend_commands() if _argv_literal(command) not in GATE]
    assert not missing, "check_all.py's frontend stage never runs " + ", ".join(repr(c) for c in missing)


def test_the_parity_guard_would_notice_a_step_added_to_ci() -> None:
    assert _argv_literal("npx stylelint src") not in GATE
    assert _argv_literal("npx eslint src") in GATE

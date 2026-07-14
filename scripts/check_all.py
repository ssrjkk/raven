"""Unified project check script.

Runs lint, import checks, per-component tests, full test suite, CLI verification,
and optionally frontend build. Provides colored pass/fail output and summary.

Usage:
    python scripts/check_all.py              # run all checks
    python scripts/check_all.py --lint       # lint only
    python scripts/check_all.py --tests      # all tests only
    python scripts/check_all.py --component core  # single component tests
    python scripts/check_all.py --frontend   # include frontend build
    python scripts/check_all.py --quick      # lint + mypy + imports + CLI only (no tests)
    python scripts/check_all.py --cov        # full run with coverage report
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

CHECK_DIRS = ["raven/", "aios/", "ravencode/", "tests/", "scripts/"]
_USE_COV = False

# -- Colors ------------------------------------------------------------------

BOLD = "\033[1m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

if not sys.stdout.isatty():
    BOLD = RED = GREEN = YELLOW = CYAN = RESET = ""

# -- Data --------------------------------------------------------------------

Status = Literal["pass", "fail", "skip"]


@dataclass
class CheckResult:
    name: str
    status: Status
    duration: float = 0.0
    detail: str = ""
    counts: dict[str, int] = field(default_factory=dict)


# -- Helpers -----------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 600, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[Any]:
    merged_env = {**os.environ, "LOGURU_LEVEL": "ERROR", **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=merged_env)  # noqa: S603 — cmd from trusted callers


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _parse_summary_line(line: str) -> tuple[int, int, int]:
    """Parse 'N passed, N failed, N skipped' from a pytest summary line."""
    passed = failed = skipped = 0
    clean = _strip_ansi(line)
    for part in clean.split(","):
        part = part.strip()
        tokens = part.split()
        if not tokens:
            continue
        try:
            n = int(tokens[0])
        except ValueError:
            continue
        if "passed" in part:
            passed = n
        elif "failed" in part:
            failed = n
        elif "skipped" in part:
            skipped = n
    return passed, failed, skipped


def _print_result(r: CheckResult) -> None:
    icon = f"{GREEN}PASS{RESET}" if r.status == "pass" else f"{RED}FAIL{RESET}" if r.status == "fail" else f"{YELLOW}SKIP{RESET}"
    time_str = f" ({r.duration:.1f}s)" if r.duration else ""
    print(f"  [{icon}]{time_str} {r.name}")
    if r.detail:
        for line in r.detail.strip().splitlines():
            print(f"         {line}")


def _print_section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'-' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'-' * 60}{RESET}")


# -- Checks ------------------------------------------------------------------

def check_ruff() -> CheckResult:
    _print_section("Lint (ruff)")
    t0 = time.time()
    r = _run([sys.executable, "-m", "ruff", "check", *CHECK_DIRS], timeout=120)
    dt = time.time() - t0
    if r.returncode == 0:
        return CheckResult("ruff check", "pass", dt)
    errors = [line for line in r.stdout.splitlines() if line.strip()]
    return CheckResult("ruff check", "fail", dt, "\n".join(errors[:20]))


def _mypy_targets() -> list[str]:
    result: list[str] = []
    for d in CHECK_DIRS:
        p = ROOT / d
        if p.is_dir() and list(p.glob("*.py")):
            py_files = sorted(str(f) for f in p.rglob("*.py") if ".venv" not in str(f) and "__pycache__" not in str(f))
            if py_files:
                result.extend(py_files)
            else:
                result.append(d)
        else:
            result.append(d)
    return result


def check_mypy() -> CheckResult:
    _print_section("Type Check (mypy)")
    t0 = time.time()
    targets = _mypy_targets()
    r = _run([sys.executable, "-m", "mypy", *targets, "--ignore-missing-imports"], timeout=120)
    dt = time.time() - t0
    if r.returncode == 0:
        return CheckResult("mypy", "pass", dt)
    errors = [line for line in (r.stdout + r.stderr).splitlines() if line.strip() and ":" in line]
    return CheckResult("mypy", "fail", dt, "\n".join(errors[:20]))


def check_imports() -> CheckResult:
    _print_section("Module Imports")
    t0 = time.time()
    sys.path.insert(0, str(ROOT))

    modules = [
        "raven.core.config",
        "raven.core.llm",
        "raven.core.db",
        "raven.core.agent.agent",
        "raven.core.agent.registry",
        "raven.core.gateway.gateway",
        "raven.core.task_engine.planner",
        "raven.core.coder.session",
        "raven.core.coder.review",
        "raven.core.sandbox",
        "raven.core.rag.retriever",
        "aios.api.bridge",
        "aios.agents.orchestrator",
        "aios.runtime.adapter",
        "ravencode",
        "ravencode.api.client",
        "ravencode.agents.orchestrator",
        "ravencode.runtime.shell",
    ]

    failed: list[str] = []
    for mod in modules:
        try:
            importlib.import_module(mod)
            print(f"  {GREEN}OK{RESET}  {mod}")
        except Exception as e:
            failed.append(mod)
            print(f"  {RED}FAIL{RESET} {mod}: {e}")

    dt = time.time() - t0
    if failed:
        return CheckResult("module imports", "fail", dt, f"{len(failed)}/{len(modules)} failed: {', '.join(failed)}")
    return CheckResult("module imports", "pass", dt, f"all {len(modules)} modules")


def check_cli_imports() -> CheckResult:
    _print_section("CLI Entry Points")
    t0 = time.time()
    sys.path.insert(0, str(ROOT))

    clis = [
        ("raven", "raven.cli.main"),
        ("ravencode", "ravencode.__main__"),
        ("ravenflow", "raven.gateway.daemon"),
    ]

    failed: list[str] = []
    for name, mod in clis:
        try:
            importlib.import_module(mod)
            print(f"  {GREEN}OK{RESET}  {name} ({mod})")
        except Exception as e:
            failed.append(name)
            print(f"  {RED}FAIL{RESET} {name}: {e}")

    dt = time.time() - t0
    if failed:
        return CheckResult("CLI imports", "fail", dt, f"failed: {', '.join(failed)}")
    return CheckResult("CLI imports", "pass", dt, f"all {len(clis)} CLIs")


COMPONENTS: dict[str, dict[str, Any]] = {
    "core": {
        "paths": ["tests/core/"],
        "ignore": ["tests/core/test_sandbox.py"],
        "desc": "Core engine (config, agents, gateway, task engine, tracing, webhooks)",
    },
    "channels": {
        "paths": ["tests/channels/"],
        "ignore": [],
        "desc": "Channel adapters (telegram, discord, webchat, etc.)",
    },
    "e2e": {
        "paths": ["tests/e2e/"],
        "ignore": [],
        "mark": "e2e",
        "desc": "End-to-end gateway tests + stress tests",
    },
    "integration": {
        "paths": ["tests/integration/"],
        "ignore": [],
        "desc": "Integration tests (DB, LLM, RAG, sandbox)",
    },
    "eval": {
        "paths": ["tests/eval/"],
        "ignore": [],
        "mark": "eval",
        "desc": "Evaluation / benchmark tests",
    },
    "unit": {
        "paths": ["tests/"],
        "ignore": [
            "tests/core/test_sandbox.py",
            "tests/e2e/",
            "tests/integration/",
            "tests/eval/",
        ],
        "desc": "Unit tests (everything except e2e/integration/eval/sandbox)",
    },
}


def check_component(name: str) -> CheckResult:
    cfg = COMPONENTS[name]
    _print_section(f"Tests: {name} -- {cfg['desc']}")
    t0 = time.time()

    cov_flag = "--cov=raven" if _USE_COV else "--no-cov"
    cmd = [
        sys.executable, "-m", "pytest",
        "-q", "--tb=short", "--timeout=120",
        "-p", "no:schemathesis",
        cov_flag,
        "-W", "ignore::RuntimeWarning",
    ]

    for p in cfg["paths"]:
        cmd.append(p)
    for ig in cfg.get("ignore", []):
        cmd.extend(["--ignore", ig])
    if "mark" in cfg:
        cmd.extend(["-m", cfg["mark"]])

    r = _run(cmd, timeout=600)
    dt = time.time() - t0

    output = _strip_ansi(r.stdout + r.stderr)
    # Parse pytest summary line like "5 passed, 1 failed in 3.21s"
    summary = ""
    passed = failed = skipped = errors = 0
    for line in output.splitlines():
        line_s = _strip_ansi(line).strip()
        if " passed" in line_s or " failed" in line_s or " error" in line_s or " skipped" in line_s:
            summary = line_s
            p, f, s = _parse_summary_line(line_s)
            passed, failed, skipped = p, f, s
            # Also check for errors
            clean = _strip_ansi(line_s)
            for part in clean.split(","):
                part = part.strip()
                if "error" in part:
                    with contextlib.suppress(ValueError):
                        errors = int(part.split()[0])

    counts = {"passed": passed, "failed": failed, "skipped": skipped, "errors": errors}

    # Print last 30 lines of output for context
    out_lines = [line for line in output.splitlines() if line.strip()]
    for line in out_lines[-30:]:
        print(f"  {line}")

    status: Status = "pass"
    detail = summary
    if r.returncode != 0:
        status = "fail"
        if failed:
            detail = f"{failed} FAILED -- {summary}"
        elif errors:
            detail = f"{errors} ERRORS -- {summary}"
        else:
            detail = summary or f"exit code {r.returncode}"

    return CheckResult(f"tests/{name}", status, dt, detail, counts)


def check_full_tests() -> CheckResult:
    _print_section("Tests: Full Suite")
    t0 = time.time()

    cov_flag = "--cov=raven" if _USE_COV else "--no-cov"
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "-q", "--tb=short", "--timeout=120",
        "--ignore=tests/core/test_sandbox.py",
        "-p", "no:schemathesis",
        cov_flag,
        "-W", "ignore::RuntimeWarning",
    ]

    r = _run(cmd, timeout=900)
    dt = time.time() - t0

    output = _strip_ansi(r.stdout + r.stderr)
    summary = ""
    passed = failed = skipped = 0
    for line in output.splitlines():
        line_s = _strip_ansi(line).strip()
        if " passed" in line_s or " failed" in line_s or " skipped" in line_s:
            summary = line_s
            p, f, s = _parse_summary_line(line_s)
            passed, failed, skipped = p, f, s

    counts = {"passed": passed, "failed": failed, "skipped": skipped}

    out_lines = [line for line in output.splitlines() if line.strip()]
    for line in out_lines[-30:]:
        print(f"  {line}")

    status: Status = "pass" if r.returncode == 0 else "fail"
    return CheckResult("tests/full", status, dt, summary, counts)


def check_frontend() -> CheckResult:
    _print_section("Frontend Build (web/)")
    web_dir = ROOT / "web"
    if not (web_dir / "package.json").exists():
        return CheckResult("frontend", "skip", detail="web/package.json not found")

    t0 = time.time()

    # Check npm ci
    r = _run(["npm", "ci"], timeout=120, env={"CI": "true"})
    if r.returncode != 0:
        return CheckResult("frontend npm ci", "fail", time.time() - t0, r.stderr[:500])

    # TypeScript check
    r = _run(["npx", "tsc", "--noEmit"], timeout=120)
    if r.returncode != 0:
        return CheckResult("frontend tsc", "fail", time.time() - t0, r.stderr[:500])

    # Build
    r = _run(["npm", "run", "build"], timeout=120)
    dt = time.time() - t0
    if r.returncode != 0:
        return CheckResult("frontend build", "fail", dt, r.stderr[:500])

    return CheckResult("frontend build", "pass", dt)


# -- Main --------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Unified project check script")
    parser.add_argument("--lint", action="store_true", help="Run ruff lint only")
    parser.add_argument("--tests", action="store_true", help="Run all tests only")
    parser.add_argument("--component", choices=list(COMPONENTS.keys()), help="Run tests for a specific component")
    parser.add_argument("--frontend", action="store_true", help="Include frontend build check")
    parser.add_argument("--quick", action="store_true", help="Lint + mypy + imports + CLI only (skip tests)")
    parser.add_argument("--cov", action="store_true", help="Include coverage report in full test run")
    args = parser.parse_args()

    run_all = not (args.lint or args.tests or args.component or args.quick)

    global _USE_COV  # noqa: PLW0603
    _USE_COV = args.cov

    print(f"\n{BOLD}{'=' * 62}{RESET}")
    print(f"{BOLD}  Raven Project -- Unified Check Script{RESET}")
    print(f"{BOLD}{'=' * 62}{RESET}")

    results: list[CheckResult] = []
    t_start = time.time()

    # Always run these
    if run_all or args.lint or args.quick:
        results.append(check_ruff())
        results.append(check_mypy())

    if run_all or args.quick:
        results.append(check_imports())
        results.append(check_cli_imports())

    # Tests
    if args.component:
        results.append(check_component(args.component))
    elif args.tests or run_all:
        results.append(check_full_tests())
        # Also run per-component breakdown
        for name in COMPONENTS:
            results.append(check_component(name))

    # Frontend
    if args.frontend or (run_all and (ROOT / "web" / "package.json").exists()):
        results.append(check_frontend())

    total_time = time.time() - t_start

    # -- Summary -------------------------------------------------------------
    _print_section("Summary")

    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")

    for r in results:
        _print_result(r)

    print(f"\n  {BOLD}Total: {len(results)} checks{RESET}  "
          f"{GREEN}{passed} passed{RESET}  "
          f"{RED}{failed} failed{RESET}  "
          f"{YELLOW}{skipped} skipped{RESET}  "
          f"({total_time:.1f}s)")

    if failed:
        print(f"\n  {RED}{BOLD}FAILED{RESET}")
        return 1
    print(f"\n  {GREEN}{BOLD}ALL PASSED{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

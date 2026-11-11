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
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

CHECK_DIRS = ["raven/", "aios/", "ravencode/", "plugins/", "tests/", "scripts/"]
# The shipped code, not the test code: a test that plants a fake secret is a test doing its job.
BANDIT_DIRS = ["raven", "ravencode", "aios", "plugins"]
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

def _resolve_exe(name: str) -> str:
    """Resolve an executable on Windows, preferring .cmd/.exe/.bat over .ps1."""
    if os.name != "nt" or Path(name).suffix:
        return name
    for ext in (".cmd", ".exe", ".bat"):
        found = shutil.which(name + ext)
        if found:
            return found
    return name


TIMEOUT_RETURNCODE = 124


def _run(
    cmd: list[str],
    timeout: int = 600,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess[Any]:
    merged_env = {**os.environ, "LOGURU_LEVEL": "ERROR", "PYTHONIOENCODING": "utf-8", **(env or {})}
    if cmd:
        cmd = [_resolve_exe(cmd[0]), *cmd[1:]]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=merged_env,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        # A killed stage is a failed stage, not a crashed run: the summary must name the stage that hit its cap.
        partial = exc.stdout if isinstance(exc.stdout, str) else ""
        return subprocess.CompletedProcess(
            cmd, TIMEOUT_RETURNCODE, stdout=partial, stderr=f"TIMED OUT after {timeout}s (process killed)"
        )


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _reset_allure_results() -> None:
    # addopts makes every run append per-test JSON here; left alone it reached 2M files and each
    # pytest start paid seconds per written result on a directory that large.
    results_dir = ROOT / "allure-results"
    if results_dir.is_dir():
        shutil.rmtree(results_dir, ignore_errors=True)


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


def _print_pytest_output(output: str, returncode: int) -> None:
    """Echo pytest output, keeping the FAILURES block on failure.

    A plain tail cuts the assertion diffs off right where the diagnosis starts,
    which is exactly the part a failing batch is read for. The totals and the
    short summary follow the block, so printing from it to the end loses nothing.
    """
    lines = [line for line in output.splitlines() if line.strip()]
    if returncode != 0:
        for idx, line in enumerate(lines):
            if "FAILURES" in line and line.startswith("="):
                for block in lines[idx : idx + 180]:
                    print(f"  {block}")
                if len(lines) - idx > 180:
                    print(f"  ... {len(lines) - idx - 180} more lines")
                return
    for line in lines[-30:]:
        print(f"  {line}")


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
    if r.returncode == TIMEOUT_RETURNCODE:
        return CheckResult("ruff check", "fail", dt, r.stderr)
    errors = [line for line in r.stdout.splitlines() if line.strip()]
    return CheckResult("ruff check", "fail", dt, "\n".join(errors[:20]))


def _mypy_targets() -> list[str]:
    targets: list[str] = []
    for d in CHECK_DIRS:
        p = ROOT / d
        if not p.exists():
            continue
        if d == "scripts/":
            targets.extend(str(f) for f in sorted(p.glob("*.py")))
        else:
            targets.append(str(p))
    return targets


def check_mypy() -> CheckResult:
    _print_section("Type Check (mypy)")
    t0 = time.time()
    targets = _mypy_targets()
    # A cold cache over 858 files measured 134.5s on the dev laptop, so a 120s cap kills a
    # passing run and reports it as a failure with no diagnostics at all.
    r = _run([sys.executable, "-m", "mypy", *targets, "--ignore-missing-imports"], timeout=300)
    dt = time.time() - t0
    if r.returncode == 0:
        return CheckResult("mypy", "pass", dt)
    if r.returncode == TIMEOUT_RETURNCODE:
        return CheckResult("mypy", "fail", dt, r.stderr)
    errors = [line for line in (r.stdout + r.stderr).splitlines() if line.strip() and ":" in line]
    return CheckResult("mypy", "fail", dt, "\n".join(errors[:20]))


# Bandit reads the ids of a `# nosec` out of the comment with these two expressions (core/manager.py).
# Anything that is not an id still lands inside the same capture, which is why prose written after the
# `# nosec` token reads as a suppression to a human and as nothing at all to bandit.
_NOSEC_COMMENT = re.compile(r"#\s*nosec:?\s*(?P<tests>[^#]+)?#?")
_NOSEC_ID = re.compile(r"(B\d+|[a-z\d_]+)", re.IGNORECASE)


def _bandit_cmd(targets: list[str], *flags: str) -> list[str]:
    return [sys.executable, "-m", "bandit", "--quiet", *flags, "-r", *targets, "-f", "json"]


def _nosec_annotations(targets: list[str]) -> Counter[tuple[str, str]]:
    """How many times each `(file, test id)` in the scanned source asks bandit to skip a finding."""
    counts: Counter[tuple[str, str]] = Counter()
    for name in targets:
        for py in sorted((ROOT / name).rglob("*.py")):
            key = str(py.resolve())
            for line in py.read_text(encoding="utf-8-sig").splitlines():
                match = _NOSEC_COMMENT.search(line)
                if match and match.group("tests"):
                    counts.update((key, test_id.upper()) for test_id in _NOSEC_ID.findall(match.group("tests")))
    return counts


def _suppressed_findings(unannotated: dict[str, Any], annotated: dict[str, Any]) -> Counter[tuple[str, str]]:
    """The findings that exist only when the `# nosec` comments are ignored — what they actually erase.

    Counted per file rather than per line: bandit reads a nosec on the line above a statement too, and
    a call that spans lines reports at the start of the expression, so a line-by-line pairing would
    call correct annotations dead.
    """
    kept = Counter((str(Path(f["filename"]).resolve()), f["test_id"].upper()) for f in annotated.get("results", []))
    every = Counter((str(Path(f["filename"]).resolve()), f["test_id"].upper()) for f in unannotated.get("results", []))
    return Counter({key: count - kept[key] for key, count in every.items() if count > kept.get(key, 0)})


def check_bandit() -> CheckResult:
    """Security lint. High or Medium findings fail the stage outright: the tree carries neither.

    A `# nosec` is a control, so it is checked like one. Bandit says on stderr when an id in one is
    not a test it knows — that annotation suppresses nothing, and the line it covers is unchecked.
    And every annotation has to erase a finding that bandit would otherwise report, measured against a
    second run with `--ignore-nosec`; an id that fires nowhere is a suppression left behind by the fix
    that made it unnecessary.
    """
    _print_section("Security lint (bandit)")
    t0 = time.time()
    targets = [d for d in BANDIT_DIRS if (ROOT / d).is_dir()]
    r = _run(_bandit_cmd(targets), timeout=240)
    dt = time.time() - t0
    try:
        report = json.loads(r.stdout)
    except ValueError:
        # The report is the measurement. A tree where bandit is not installed, or died on the way,
        # has not been checked — so this is a failure, not a skip.
        return CheckResult("bandit", "fail", dt, (r.stderr.strip() or r.stdout.strip() or "no report")[:1200])
    totals = report.get("metrics", {}).get("_totals", {})
    findings = [f for f in report.get("results", []) if f.get("issue_severity") in ("HIGH", "MEDIUM")]
    counts = {
        "high": sum(1 for f in findings if f.get("issue_severity") == "HIGH"),
        "medium": sum(1 for f in findings if f.get("issue_severity") == "MEDIUM"),
        "low": int(totals.get("SEVERITY.LOW", 0)),
    }
    errors = report.get("errors") or []
    if errors:
        return CheckResult("bandit", "fail", dt, f"bandit could not parse: {json.dumps(errors)[:1200]}", counts)
    inert = [line for line in r.stderr.splitlines() if "is not a test name or id" in line]
    if inert:
        detail = "\n".join(line.strip() for line in inert[:20])
        return CheckResult(
            "bandit", "fail", dt, f"nosec ids bandit does not know (they suppress nothing):\n{detail}", counts
        )
    annotations = _nosec_annotations(targets)
    if annotations:
        again = _run(_bandit_cmd(targets, "--ignore-nosec"), timeout=240)
        try:
            unpinned = json.loads(again.stdout)
        except ValueError:
            return CheckResult("bandit", "fail", dt, (again.stderr.strip() or "no report")[:1200], counts)
        erased = _suppressed_findings(unpinned, report)
        dead = sorted(
            f"{Path(name).relative_to(ROOT)} {test_id}"
            for (name, test_id), count in annotations.items()
            if not count <= erased.get((name, test_id), 0)
        )
        if dead:
            detail = "\n".join(dead[:20])
            return CheckResult("bandit", "fail", dt, f"nosec annotations that suppress nothing:\n{detail}", counts)
    counts["nosec"] = sum(annotations.values())
    if not findings:
        return CheckResult("bandit", "pass", dt, f"{counts['low']} low-severity notes", counts)
    detail = "\n".join(f"{f['filename']}:{f['line_number']} {f['test_id']} {f['issue_text']}" for f in findings[:20])
    return CheckResult("bandit", "fail", dt, detail, counts)


def check_imports() -> CheckResult:
    _print_section("Module Imports")
    t0 = time.time()
    sys.path.insert(0, str(ROOT))

    modules = [
        "raven.core.config",
        "raven.core.llm",
        "raven.core.llm.router",
        "raven.core.db",
        "raven.core.auth.oauth",
        "raven.core.auth.password",
        "raven.core.auth.store",
        "raven.core.auth.tokens",
        "raven.core.cache.redis_client",
        "raven.core.cache.session_store",
        "raven.core.cache.llm_cache",
        "raven.core.gateway.gateway",
        "raven.core.gateway.channel_manager",
        "raven.core.gateway.message_processor",
        "raven.core.gateway.task_orchestrator",
        "raven.core.security.rate_limiter",
        "raven.core.security.policy_engine",
        "raven.core.security.sandbox_policy",
        "raven.core.security.ssrf",
        "raven.core.agent.agent",
        "raven.core.agent.registry",
        "raven.core.task_engine.planner",
        "raven.core.task_engine.runner",
        "raven.core.task_engine.store",
        "raven.core.task_engine.models",
        "raven.core.coder.session",
        "raven.core.coder.review",
        "raven.core.coder.analyzer",
        "raven.core.sandbox",
        "raven.core.rag.retriever",
        "raven.core.rag.vector_store",
        "raven.core.rag.embeddings",
        "raven.core.monitor.engine",
        "raven.core.monitor.store",
        "raven.core.channel_guardian",
        "raven.core.context_router",
        "raven.core.cost_management",
        "raven.core.failover",
        "raven.core.metrics",
        "raven.tools.file",
        "raven.tools.shell",
        "aios.api.bridge",
        "aios.agents.orchestrator",
        "aios.runtime.adapter",
        "ravencode",
        "ravencode.api.client",
        "ravencode.agents.orchestrator",
        "ravencode.runtime.shell",
        "ravencode.runtime.context",
        "ravencode.runtime.tools",
        "ravencode.integrations.github_webhook",
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
        # Measured 622-707s for 6628 tests with the box otherwise idle, and killed at 89% by the
        # old 1200s cap when another session was competing for CPU. The margin has to absorb a
        # contended machine, not just an idle one: 1800s matches the full-suite stage.
        "timeout": 1800,
        "desc": "Unit tests (everything except e2e/integration/eval/sandbox)",
    },
}


def _failure_detail(summary: str, output: str, returncode: int, stderr: str) -> str:
    """What a failed stage prints when it never printed a summary line.

    A pytest run that dies in its own reporting phase produces no `N passed, M failed` line at
    all - measured on this box when pytest-benchmark computed medians over the full suite on an
    8 GB machine and raised MemoryError after 7000 tests. The stage used to report a bare [FAIL]
    with an empty detail, which is a red gate with nothing to read, so the tail of the run's own
    output stands in."""
    if returncode == TIMEOUT_RETURNCODE:
        return stderr
    if summary:
        return summary
    tail = [line for line in output.splitlines() if line.strip()]
    return "\n".join(tail[-12:]) or f"exit code {returncode}, no output captured"


def check_component(name: str) -> CheckResult:
    cfg = COMPONENTS[name]
    _print_section(f"Tests: {name} -- {cfg['desc']}")
    t0 = time.time()

    cov_flag = "--no-cov"
    cmd = [
        sys.executable, "-m", "pytest",
        "-q", "--tb=short", "--timeout=120",
        "-p", "no:schemathesis",
        cov_flag,
        "-W", "ignore::RuntimeWarning",
    ]

    cmd.extend(cfg["paths"])
    for ig in cfg.get("ignore", []):
        cmd.extend(["--ignore", ig])
    if "mark" in cfg:
        cmd.extend(["-m", cfg["mark"]])

    r = _run(cmd, timeout=int(cfg.get("timeout", 600)))
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

    _print_pytest_output(output, r.returncode)

    status: Status = "pass"
    detail = summary
    if r.returncode != 0:
        status = "fail"
        if failed:
            detail = f"{failed} FAILED -- {summary}"
        elif errors:
            detail = f"{errors} ERRORS -- {summary}"
        else:
            detail = _failure_detail(summary, output, r.returncode, r.stderr)

    return CheckResult(f"tests/{name}", status, dt, detail, counts)


def check_full_tests() -> CheckResult:
    _print_section("Tests: Full Suite")
    t0 = time.time()

    # pytest-benchmark keeps every round of every @pytest.mark.benchmark test and computes its
    # stats when the session ends; on this box that reporting phase raised MemoryError after 7000
    # tests and failed the stage with no assertion behind it. The same tests are timed in full by
    # the `unit` stage (tests/benchmarks is inside its path set), so what is switched off here is
    # measuring the same benchmark twice in one gate run - not benchmarking itself.
    cov_flag = "--cov=raven" if _USE_COV else "--no-cov"
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/",
        "-q", "--tb=short", "--timeout=120",
        "--ignore=tests/core/test_sandbox.py",
        "-p", "no:schemathesis",
        "--benchmark-disable",
        cov_flag,
        "-W", "ignore::RuntimeWarning",
    ]

    r = _run(cmd, timeout=1800)
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

    _print_pytest_output(output, r.returncode)

    status: Status = "pass" if r.returncode == 0 else "fail"
    detail = summary if r.returncode == 0 else _failure_detail(summary, output, r.returncode, r.stderr)
    return CheckResult("tests/full", status, dt, detail, counts)


def check_frontend() -> CheckResult:
    _print_section("Frontend Build (web/)")
    web_dir = ROOT / "web"
    if not (web_dir / "package.json").exists():
        return CheckResult("frontend", "skip", detail="web/package.json not found")

    t0 = time.time()

    # Measured on this box with nothing else running: npm ci 43s, tsc 9s, eslint 2s, vitest 12s,
    # build 11s. The machine shares up to eight concurrent sessions, so each step gets a multiple
    # of its idle cost rather than a cap that a loaded machine blows through and reports as a code
    # failure. The five steps are the five the `frontend` job in ci.yml runs, in that order: the
    # stage used to stop at tsc and build, so an eslint error added by a translated string landed on
    # main green locally and red in CI (simple-import-sort in command-keywords.test.ts).
    r = _run(["npm", "ci"], timeout=600, env={"CI": "true"}, cwd=web_dir)
    if r.returncode != 0:
        return CheckResult("frontend npm ci", "fail", time.time() - t0, r.stderr[:500])

    r = _run(["npx", "tsc", "--noEmit"], timeout=300, cwd=web_dir)
    if r.returncode != 0:
        return CheckResult("frontend tsc", "fail", time.time() - t0, r.stderr[:500])

    r = _run(["npx", "eslint", "src"], timeout=300, cwd=web_dir)
    if r.returncode != 0:
        return CheckResult("frontend eslint", "fail", time.time() - t0, (r.stdout + r.stderr)[:500])

    r = _run(["npm", "test", "--", "--run"], timeout=600, cwd=web_dir)
    if r.returncode != 0:
        return CheckResult("frontend vitest", "fail", time.time() - t0, (r.stdout + r.stderr)[:500])

    r = _run(["npm", "run", "build"], timeout=300, cwd=web_dir)
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

    global _USE_COV
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
        results.append(check_bandit())

    if run_all or args.quick:
        results.append(check_imports())
        results.append(check_cli_imports())

    # Tests
    if args.component or args.tests or run_all:
        _reset_allure_results()
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

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

from raven.qa_healer.analyzer import FailureReport, TestFailure

_WORKSPACE_DIR = Path(os.getenv("RAVEN_WORKSPACE", "workspace")).resolve()


def _confine(p: Path) -> Path:
    p = p.resolve()
    if _WORKSPACE_DIR not in p.parents and p != _WORKSPACE_DIR:
        raise ValueError(f"Path {p} is outside workspace {_WORKSPACE_DIR}")
    return p


async def _ensure_agent() -> Any:
    from ravencode.agents.orchestrator import Orchestrator

    return Orchestrator()


def _is_playwright_test(file_path: str | Path) -> bool:
    return ".spec." in str(file_path) and str(file_path).endswith((".ts", ".js", ".mjs"))


def _is_selenium_test(file_path: str | Path) -> bool:
    f = Path(file_path)
    if not f.exists():
        return False
    text = f.read_text("utf-8")
    return "selenium" in text or "webdriver" in text


def _find_test_file(test_name: str, search_root: Path = _WORKSPACE_DIR) -> Path | None:
    search_root = _confine(search_root)
    for p in search_root.rglob("*.spec.*"):
        content = p.read_text("utf-8", errors="replace")
        if test_name.split(" ")[0] in content or test_name in content:
            return p
    name_parts = test_name.replace(" ", "_").replace("/", ".").split(".")
    for p in search_root.rglob("*"):
        if p.is_file() and any(part in p.name for part in name_parts if len(part) > 3):
            return p
    return None


def _find_screenshot(failure: TestFailure, search_root: Path = _WORKSPACE_DIR) -> str | None:
    if failure.screenshot_path and Path(failure.screenshot_path).exists():
        return failure.screenshot_path
    name_base = Path(failure.test_file).stem.replace(".spec", "")
    for ext in [".png", ".jpg"]:
        for p in search_root.rglob(f"*{name_base}*{ext}"):
            return str(p)
    return None


def _build_fix_prompt(failure: TestFailure, test_content: str, screenshot_summary: str = "") -> str:
    prompt = f"""You are a QA Self-Healer. A test is failing and you must fix it.

## Test file: {failure.test_file}
## Test name: {failure.test_name}

## Error message:
```
{failure.error_message}
```

## Stack trace:
```
{failure.stack_trace or "Not available"}
```

## Current test content:
```python
{test_content}
```

{screenshot_summary}
## Instructions:
1. Analyze the error and the test content carefully.
2. Identify the root cause: is it a broken locator, changed behavior, wrong assertion, or environment issue?
3. Fix the test by editing the file.
4. Run the test to verify the fix works (use the appropriate test command).
5. If the fix is correct, commit the changes with a descriptive message.

Focus on minimal, precise fixes. Do not change test logic unless necessary to match the actual application behavior."""
    return prompt


async def heal_test_failure(
    failure: TestFailure,
    repo_path: str | Path = ".",
    branch_prefix: str = "raven/heal",
    auto_pr: bool = False,
) -> dict[str, Any]:
    repo = _confine(Path(repo_path).resolve())
    if not (repo / ".git").is_dir():
        repo = _WORKSPACE_DIR
    test_file = repo / Path(failure.test_file).name
    if not test_file.exists():
        test_file = _find_test_file(failure.test_name, repo) or test_file
    if not test_file.exists():
        return {"success": False, "error": f"Test file not found: {failure.test_file}", "fix_applied": False}
    test_content = test_file.read_text("utf-8", errors="replace")
    screenshot_path = _find_screenshot(failure, repo)
    screenshot_summary = ""
    if screenshot_path:
        screenshot_summary = f"A screenshot of the failure is available at: {screenshot_path}"
    prompt = _build_fix_prompt(failure, test_content, screenshot_summary)
    orchestrator = await _ensure_agent()
    branch = f"{branch_prefix}/{failure.test_name[:30].replace(' ', '-').replace('/', '-')}"
    try:
        _run_git(repo, "checkout", "-b", branch)
    except Exception:
        logger.debug("[healer] Branch exists, checking out anyway")
        _run_git(repo, "checkout", "-b", branch)
    from ravencode.agents.orchestrator import AgentType

    result = await orchestrator.dispatch(prompt, AgentType.CODER)
    if not result.success:
        return {"success": False, "error": result.error or "Fix failed", "fix_applied": False, "branch": branch}
    try:
        _run_git(repo, "add", "-A")
        _run_git(repo, "commit", "-m", f"fix({failure.test_file}): auto-heal {failure.test_name[:60]}")
    except Exception as exc:
        logger.warning("Git commit failed: {}", exc)
    pr_number = None
    if auto_pr:
        try:
            _run_git(repo, "push", "origin", branch)
            from ravencode.integrations.vcs import create_vcs_provider

            gh_token = os.environ.get("GITHUB_TOKEN", "")
            gh = create_vcs_provider("github", token=gh_token)
            owner = _run_git(repo, "remote", "get-url", "origin").split("/")[-2] if "/" in _run_git(repo, "remote", "get-url", "origin") else ""
            repo_name = repo.name
            if owner and repo_name:
                pr = await gh.create_pull_request(
                    f"{owner}/{repo_name}",
                    title=f"Fix: {failure.test_name[:60]}",
                    source=branch,
                    target="main",
                    body=f"## Auto-fix by Raven QA Healer\n\n### Failure\n```\n{failure.error_message}\n```\n\n### Test\n`{failure.test_file}`",
                )
                pr_number = pr.id
        except Exception as exc:
            logger.warning("Auto-PR failed: {}", exc)
    return {
        "success": True,
        "branch": branch,
        "pr_number": pr_number,
        "fix_applied": True,
        "test_file": str(test_file),
    }


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(repo),
        timeout=60,
    )
    if result.returncode != 0:
        error_msg = result.stderr.strip()
        if "nothing to commit" in error_msg or "already exists" in error_msg:
            return result.stdout.strip() or error_msg
        raise RuntimeError(f"git {' '.join(args)} failed: {error_msg}")
    return result.stdout.strip()


async def heal_all_failures(
    report: FailureReport,
    repo_path: str | Path = ".",
    branch_prefix: str = "raven/heal",
    auto_pr: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for failure in report.failures:
        logger.info("Healing: {}", failure.test_name)
        try:
            result = await heal_test_failure(failure, repo_path, branch_prefix, auto_pr)
            results.append(result)
        except Exception as exc:
            logger.error("Failed to heal {}: {}", failure.test_name, exc)
            results.append({"success": False, "error": str(exc), "test_name": failure.test_name, "fix_applied": False})
    return results


async def qa_heal_all(
    results_dir: str = "",
    repo_path: str = ".",
    auto_pr: bool = False,
) -> str:
    from raven.qa_healer.analyzer import analyze_test_failure

    if not results_dir:
        return "No results directory provided"
    report = await analyze_test_failure(results_dir)
    if not report.failures:
        return f"No failures found. {report.summary}"
    results = await heal_all_failures(report, repo_path, auto_pr=auto_pr)
    fixed = sum(1 for r in results if r.get("fix_applied"))
    failed_heal = sum(1 for r in results if not r.get("fix_applied"))
    lines = [
        "## Raven QA Healer Report",
        f"- Total failures: {len(report.failures)}",
        f"- Fixed: {fixed}",
        f"- Failed to heal: {failed_heal}",
    ]
    for r in results:
        if r.get("fix_applied"):
            lines.append(f"  ✓ {r.get('test_file', '?')} → branch: {r.get('branch', '?')} PR: {r.get('pr_number', 'N/A')}")
        else:
            lines.append(f"  ✗ {r.get('test_name', r.get('test_file', '?'))}: {r.get('error', 'Unknown')}")
    return "\n".join(lines)

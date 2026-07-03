from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

PLUGIN_NAME = "qa_healer"
PLUGIN_DESCRIPTION = "QA Self-Healer — analyze and auto-fix test failures from Allure/GitHub Actions"


async def qa_analyze(results_dir_or_payload: str) -> str:
    """Analyze test failure results from an Allure directory or GitHub Actions JSON payload.

    Args:
        results_dir_or_payload: Path to allure-results directory, path to a log file, or a JSON string of GitHub Actions webhook payload.
    """
    from raven.qa_healer.analyzer import analyze_test_failure

    payload: str | dict[str, Any] = results_dir_or_payload
    if results_dir_or_payload.startswith("{"):
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(results_dir_or_payload)
    report = await analyze_test_failure(payload)
    lines = [report.summary]
    for f in report.failures:
        lines.append(f"  - {f.test_name} ({f.test_file}): {f.error_message[:120]}")
    return "\n".join(lines) if lines else "No failures found"


async def qa_heal_failure(
    test_file: str,
    error_message: str,
    stack_trace: str = "",
    test_name: str = "",
    screenshot_path: str = "",
    repo_path: str = ".",
) -> str:
    """Heal a single test failure using the RavenCode coding agent.

    Args:
        test_file: Path to the test file relative to repository root.
        error_message: The error message from the test failure.
        stack_trace: Optional full stack trace.
        test_name: Optional test name for the commit message.
        screenshot_path: Optional path to a screenshot of the failure.
        repo_path: Path to the git repository root.
    """
    from raven.qa_healer.analyzer import TestFailure
    from raven.qa_healer.healer import heal_test_failure

    failure = TestFailure(
        test_name=test_name or Path(test_file).stem,
        test_file=test_file,
        error_message=error_message,
        stack_trace=stack_trace,
        screenshot_path=screenshot_path or None,
    )
    result = await heal_test_failure(failure, repo_path)
    if result.get("fix_applied"):
        branch = result.get("branch", "?")
        return f"Fix applied. Branch: {branch}. Test: {test_file}"
    return f"Failed to heal: {result.get('error', 'Unknown error')}"


async def qa_heal_all(results_dir: str, repo_path: str = ".", auto_pr: bool = False) -> str:
    """Analyze all failures in an Allure results directory and heal them.

    Args:
        results_dir: Path to the allure-results directory.
        repo_path: Path to the git repository root.
        auto_pr: If true, push branch and create a GitHub PR.
    """
    from raven.qa_healer.healer import qa_heal_all as _heal_all

    return await _heal_all(results_dir, repo_path, auto_pr)

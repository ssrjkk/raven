from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class TestFailure:
    test_name: str
    test_file: str
    error_message: str
    stack_trace: str = ""
    screenshot_path: str | None = None
    dom_snapshot: str | None = None
    video_path: str | None = None
    trace_path: str | None = None


@dataclass
class FailureReport:
    failures: list[TestFailure] = field(default_factory=list)
    suite_name: str = ""
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_sec: float = 0.0

    @property
    def summary(self) -> str:
        return (
            f"Suite: {self.suite_name} | "
            f"{self.passed}/{self.total_tests} passed, "
            f"{self.failed} failed, "
            f"{self.skipped} skipped "
            f"({self.duration_sec:.1f}s)"
        )


_PLAYWRIGHT_ERROR_RE = re.compile(
    r"(?P<file>tests?/[\w/.-]+\.spec\.[\w]+):(?P<line>\d+)\s+[›>]\s+(?P<name>.+?)\n(?:.*\n){0,50}?\s+Error:\s*(?P<error>.+?)(?:\n\s+at\s|\Z)",
    re.MULTILINE | re.DOTALL,
)

_PLAYWRIGHT_TRACE_RE = re.compile(r"(?P<file>tests?/[\w/.-]+\.spec\.[\w]+):(?P<line>\d+)")

_ALLURE_RESULT_RE = re.compile(r"[\w-]+-result\.json$")


class AllureAnalyzer:
    def __init__(self, results_dir: str | Path) -> None:
        self.results_dir = Path(results_dir)

    def analyze(self) -> FailureReport:
        if not self.results_dir.is_dir():
            logger.warning("Allure results directory not found: {}", self.results_dir)
            return FailureReport()
        report = FailureReport()
        json_files = [f for f in self.results_dir.iterdir() if f.is_file() and _ALLURE_RESULT_RE.search(f.name)]
        for jf in sorted(json_files):
            try:
                data = json.loads(jf.read_text("utf-8"))
                self._parse_result(data, report)
            except Exception as exc:
                logger.warning("Failed to parse {}: {}", jf.name, exc)
        report.total_tests = report.passed + report.failed + report.skipped
        logger.info("Allure analysis: {}", report.summary)
        return report

    def _parse_result(self, data: dict[str, Any], report: FailureReport) -> None:
        status = data.get("status", "unknown")
        name = data.get("name", "unnamed")
        full_name = data.get("fullName", name)
        if status == "passed":
            report.passed += 1
            return
        if status == "skipped":
            report.skipped += 1
            return
        if status == "failed" or status == "broken":
            report.failed += 1
            test_file = full_name.split("/")[-1] if "/" in full_name else name
            error_message = ""
            stack_trace = ""
            status_details = data.get("statusDetails", {}) or {}
            if status_details:
                error_message = status_details.get("message", "") or ""
                stack_trace = status_details.get("trace", "") or ""
            labels = data.get("labels", [])
            for lb in labels:
                if lb.get("name") == "testMethod" and lb.get("value"):
                    test_file = lb["value"]
            attachments = data.get("attachments", [])
            screenshot = None
            dom = None
            video = None
            trace = None
            for att in attachments:
                name_lower = att.get("name", "").lower()
                source = att.get("source", "")
                if "screenshot" in name_lower or "png" in att.get("type", ""):
                    screenshot = str(self.results_dir / source)
                elif "dom" in name_lower:
                    dom_path = self.results_dir / source
                    if dom_path.exists():
                        dom = dom_path.read_text("utf-8")
                elif "video" in name_lower:
                    video = str(self.results_dir / source)
                elif "trace" in name_lower:
                    trace = str(self.results_dir / source)
            report.failures.append(
                TestFailure(
                    test_name=name,
                    test_file=test_file,
                    error_message=error_message,
                    stack_trace=stack_trace,
                    screenshot_path=screenshot,
                    dom_snapshot=dom,
                    video_path=video,
                    trace_path=trace,
                )
            )


class GitHubActionsAnalyzer:
    def __init__(self, workflow_run_payload: dict[str, Any] | None = None) -> None:
        self.payload = workflow_run_payload or {}

    def analyze(self, log_text: str | None = None) -> FailureReport:
        report = FailureReport()
        if not log_text:
            log_text = self.payload.get("steps", [{}])[0].get("logs", "") if self.payload.get("steps") else ""
        if not log_text:
            return report
        report.suite_name = self.payload.get("name", "GitHub Actions Run")
        for match in _PLAYWRIGHT_ERROR_RE.finditer(log_text):
            report.failed += 1
            report.failures.append(
                TestFailure(
                    test_name=match.group("name"),
                    test_file=match.group("file"),
                    error_message=match.group("error"),
                    stack_trace=match.group(0),
                )
            )
        passed_count = len(re.findall(r"(?:✓|✔|PASS)\s", log_text[:200000]))
        report.passed = passed_count
        report.total_tests = report.passed + report.failed + report.skipped
        report.duration_sec = 0.0
        dur_match = re.search(r"(\d+\.?\d*)\s*(?:s|seconds)", log_text)
        if dur_match:
            report.duration_sec = float(dur_match.group(1))
        logger.info("GitHub Actions analysis: {}", report.summary)
        return report


_ALLOWED_RESULTS_DIRS = {"results", "allure-results", "test-results", "playwright-results"}


async def analyze_test_failure(path_or_payload: str | dict[str, Any]) -> FailureReport:
    if isinstance(path_or_payload, str):
        p = Path(path_or_payload).resolve()
        allowed = any(parent.name in _ALLOWED_RESULTS_DIRS for parent in [p, *p.parents])
        if not allowed:
            logger.warning("Path not in allowed results directories: {}", p)
            return FailureReport()
        if p.is_dir() and any(_ALLURE_RESULT_RE.search(f.name) for f in p.iterdir()):
            return AllureAnalyzer(p).analyze()
        if p.is_file():
            text = p.read_text("utf-8")
            return GitHubActionsAnalyzer().analyze(text)
        return FailureReport()
    return GitHubActionsAnalyzer(path_or_payload).analyze()

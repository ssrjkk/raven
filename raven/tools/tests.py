from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_SAFE_ARGS_PREFIXES = (
    "-q",
    "-x",
    "--maxfail",
    "--tb",
    "--no-header",
    "--no-cov",
    "--disable-warnings",
    "--timeout",
    "--cov",
    "--cov-fail-under",
    "-k",
    "-m",
    "-rf",
    "--ff",
    "--lf",
    "-p",
)


def _workspace() -> Path:
    return Path(os.environ.get("RAVEN_WORKSPACE", "data")).resolve()


def _confine(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    ws = _workspace()
    try:
        p.relative_to(ws)
    except ValueError:
        msg = f"Access denied: path outside workspace: {p}"
        raise PermissionError(msg) from None
    return p


def _sanitize_extra_args(extra_args: str) -> tuple[str, list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for token in extra_args.split():
        if any(token.startswith(prefix) for prefix in _SAFE_ARGS_PREFIXES):
            kept.append(token)
        else:
            dropped.append(token)
    if dropped:
        logger.warning("[tests] dropping unsafe pytest args: {}", " ".join(dropped))
    return " ".join(kept), dropped


async def run_tests(path: str = "", marker: str = "", timeout: int = 120, extra_args: str = "") -> str:
    try:
        root = _confine(path) if path else Path.cwd()
    except PermissionError as e:
        return f"{e}"
    if not root.is_dir():
        return f"Path not found: {root}"
    safe_args, _dropped = _sanitize_extra_args(extra_args)
    cmd = [sys.executable, "-m", "pytest", str(root), "-q", "--tb=short", "--no-header", "-p", "no:schemathesis"]
    if marker:
        cmd += ["-m", marker]
    if safe_args:
        cmd += safe_args.split()
    logger.info("Running tests: {}", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        return f"Tests timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"pytest not found: {e}"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    lines = out.splitlines()
    summary = [ln for ln in lines if ln.startswith("==") and ("passed" in ln or "failed" in ln or "error" in ln)]
    return (
        f"Exit code: {proc.returncode}\n"
        f"Tests: {summary[0] if summary else 'unknown'}\n"
        f"{'Stderr: ' + err[:500] if err else ''}"
    )


async def test_coverage(path: str = "", timeout: int = 180) -> str:
    try:
        root = _confine(path) if path else Path.cwd()
    except PermissionError as e:
        return f"{e}"
    if not root.is_dir():
        return f"Path not found: {root}"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(root),
        "-q",
        "--tb=short",
        "--no-header",
        "-p",
        "no:schemathesis",
        "--cov=raven",
        "--cov-report=xml:coverage.xml",
        "--cov-config=.coveragerc",
    ]
    logger.info("Running coverage: {}", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        return f"Coverage run timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"pytest not found: {e}"

    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    cov_file = root / "coverage.xml"
    total = 0.0
    if cov_file.exists():
        try:
            from defusedxml.ElementTree import parse as safe_parse

            tree = safe_parse(str(cov_file))
            root_elem = tree.getroot()
            total = float(root_elem.attrib.get("line-rate", 0)) * 100
            cov_file.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Failed to parse coverage.xml: {}", e)

    lines = out.splitlines()
    summary = [ln for ln in lines if ln.startswith("==") and ("passed" in ln or "failed" in ln or "error" in ln)]
    return (
        f"Exit code: {proc.returncode}\n"
        f"Coverage: {total:.1f}%\n"
        f"Tests: {summary[0] if summary else 'unknown'}\n"
        f"{'Stderr: ' + err[:500] if err else ''}"
    )


async def generate_tests(file_path: str = "") -> str:
    if not file_path:
        return "file_path required"
    try:
        fp = _confine(file_path)
    except PermissionError as e:
        return f"{e}"
    if not fp.is_file():
        return f"File not found: {fp}"
    try:
        from raven.coding.test_generator import TestGenerator

        gen = TestGenerator()
        test_content = await gen.generate_tests(str(fp))
        if not test_content.strip() or test_content.startswith("# File not found"):
            return "No tests generated (empty or unsupported)"
        result = await gen.save_tests(str(fp), test_content)
        return f"{result}\n\n{test_content[:2000]}"
    except Exception as e:
        logger.exception("test generation failed")
        return f"Test generation error: {e}"


def register_test_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="run_tests",
            description="Run pytest tests on a given path with optional marker filter",
            parameters={
                "path": {"type": "string", "description": "Directory path to run tests on", "required": False},
                "marker": {
                    "type": "string",
                    "description": "pytest marker expression (e.g. 'not slow')",
                    "required": False,
                },
                "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
                "extra_args": {"type": "string", "description": "Extra pytest CLI args", "required": False},
            },
            handler=run_tests,
            category="development",
            timeout=200,
        )
    )
    registry.register(
        ToolSpec(
            name="test_coverage",
            description="Run pytest with coverage and return coverage percentage",
            parameters={
                "path": {"type": "string", "description": "Directory path", "required": False},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
            },
            handler=test_coverage,
            category="development",
            timeout=200,
        )
    )
    registry.register(
        ToolSpec(
            name="generate_tests",
            description="Auto-generate pytest test file from a Python source file",
            parameters={
                "file_path": {"type": "string", "description": "Path to Python source file", "required": True},
            },
            handler=generate_tests,
            category="development",
            timeout=60,
        )
    )

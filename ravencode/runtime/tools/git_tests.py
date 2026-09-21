from __future__ import annotations

import asyncio
import re
import shlex
import sys
from pathlib import Path

from loguru import logger

from ravencode.runtime.workspace import (
    confine as _confine,
)

from ._truncate import smart_truncate

# ---------------------------------------------------------------------------
# git tools
# ---------------------------------------------------------------------------


async def _git_cmd(*args: str, cwd: str | None = None) -> str:
    cmd = ["git", *list(args)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd or str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except (ProcessLookupError, OSError):
            logger.debug("git process already exited during timeout kill")
        return "[timeout]"
    output = (stdout or b"").decode("utf-8", errors="replace")[:20_000]
    if stderr:
        output += "\n" + stderr.decode("utf-8", errors="replace")[:5_000]
    if proc.returncode:
        output += f"\n[exit code: {proc.returncode}]"
    return output




async def git_status(path: str | None = None) -> str:
    return await _git_cmd("status", cwd=path)




async def git_diff(path: str | None = None, staged: bool = False) -> str:
    args = ["diff", "--cached"] if staged else ["diff"]
    return await _git_cmd(*args, cwd=path)




async def git_log(max_count: int = 10, path: str | None = None) -> str:
    return await _git_cmd("log", f"--max-count={max_count}", "--oneline", cwd=path)




async def git_commit(message: str, path: str | None = None) -> str:
    return await _git_cmd("commit", "-m", message, cwd=path)




async def git_add(files: str, path: str | None = None) -> str:
    return await _git_cmd("add", *files.split(), cwd=path)




# ---------------------------------------------------------------------------
# test running
# ---------------------------------------------------------------------------

_RUN_TESTS_TIMEOUT = 600.0


_RUN_TESTS_MAX_FAILURES = 10


# matches "5 passed in 0.42s" / "1 failed, 4 passed in 0.31s" / "2 errors in 1.0s"
# with or without the "=" banner (quiet mode omits it)
_PYTEST_SUMMARY_RE = re.compile(r"\d+ (?:passed|failed|error)s?\b.*in \d", re.IGNORECASE)




def _summarize_pytest(output: str, returncode: int) -> str:
    """Compress pytest output to failures + summary (models drown in raw logs)."""
    lines = output.splitlines()
    failed = [
        ln
        for ln in lines
        if ln.startswith(("FAILED ", "ERROR "))
        or (" - " in ln and (ln.startswith("FAILED") or ln.startswith("ERROR")))
    ][: 2 * _RUN_TESTS_MAX_FAILURES]
    summary = next(
        (ln for ln in reversed(lines) if _PYTEST_SUMMARY_RE.search(ln)),
        None,
    )
    if returncode == 0:
        return f"[tests PASS] {summary or 'all tests passed'}"
    parts = ["[tests FAIL]"]
    if summary:
        parts.append(summary)
    if failed:
        parts.append("failing:")
        parts.extend(f"  {ln}" for ln in failed)
    else:
        # crash before collection finished — keep the tail (has the traceback)
        tail = "\n".join(lines[-25:])
        parts.append(tail)
    result = "\n".join(parts)
    return smart_truncate(result, limit=4_000)




async def run_tests(path: str | None = None, extra_args: str | None = None) -> str:
    """Run pytest inside the workspace and return a token-efficient summary."""
    try:
        cwd = _confine(path) if path else _confine(".")
    except PermissionError as exc:
        return f"[error] {exc}"
    if not (Path(cwd) / "pyproject.toml").exists() and not any(Path(cwd).glob("test_*.py")) and not any(
        Path(cwd).glob("*_test.py")
    ) and not (Path(cwd) / "tests").exists():
        return "[error] no tests found here (no tests/ dir, no test_*.py, no pyproject.toml)"
    args = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-rf", "--no-header", "-p", "no:cacheprovider"]
    if extra_args:
        args.extend(shlex.split(extra_args))
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_RUN_TESTS_TIMEOUT)
    except TimeoutError:
        return f"[error] test run timed out after {int(_RUN_TESTS_TIMEOUT)}s"
    except OSError as exc:
        return f"[error] failed to launch pytest: {exc}"
    return _summarize_pytest(out.decode("utf-8", errors="replace"), proc.returncode or 0)

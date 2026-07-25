"""Auto git commit — smart analysis and auto-commit with descriptions."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger


async def _git(*args: str, cwd: str | None = None) -> str:
    cmd = ["git", *list(args)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd or Path.cwd(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except TimeoutError:
        return "[timeout]"
    output = (stdout or b"").decode("utf-8", errors="replace")[:10_000]
    if stderr:
        output += "\n" + stderr.decode("utf-8", errors="replace")[:5_000]
    if proc.returncode:
        output += f"\n[exit code: {proc.returncode}]"
    return output.strip()


def _guess_commit_type(files: list[str], diffs: list[str]) -> str:
    types: list[str] = []
    for f in files:
        if f.endswith(".py"):
            types.append("feat" if "def " in "".join(diffs) else "fix")
        elif f.endswith((".ts", ".tsx", ".js", ".jsx")):
            types.append("feat" if "function" in "".join(diffs) else "fix")
        elif f.endswith((".md", ".rst")):
            types.append("docs")
        elif f.endswith((".yml", ".yaml", ".toml", ".json")):
            types.append("chore")
        elif f.endswith((".pyi", ".go", ".rs")):
            types.append("feat")
        else:
            types.append("chore")
    if "feat" in types:
        return "feat"
    if "fix" in types:
        return "fix"
    if "docs" in types:
        return "docs"
    return "chore"


def _summarize_diff(diff: str, max_lines: int = 5) -> str:
    lines = diff.splitlines()
    summary = []
    for line in lines:
        if (line.startswith("+") and not line.startswith("+++")) or (line.startswith("-") and not line.startswith("---")):
            summary.append(line[1:80])
        if len(summary) >= max_lines:
            break
    return "; ".join(summary) if summary else "(no meaningful changes)"


async def auto_commit(path: str | None = None, message: str | None = None) -> str:
    status_raw = await _git("status", "--porcelain", cwd=path)
    if not status_raw or status_raw.startswith("[exit"):
        return status_raw if status_raw else "(nothing to commit)"

    changed_files = [line[3:].strip() for line in status_raw.splitlines() if line.strip()]

    if not changed_files:
        return "(nothing to commit)"

    await _git("add", "-A", cwd=path)
    diff = await _git("diff", "--cached", cwd=path)

    if message:
        commit_msg = message
    else:
        commit_type = _guess_commit_type(changed_files, [diff])
        summary = _summarize_diff(diff)
        paths_str = ", ".join(changed_files[:5])
        if len(changed_files) > 5:
            paths_str += f" and {len(changed_files) - 5} more"
        commit_msg = f"{commit_type}: {summary or paths_str}"

    await _git("commit", "-m", commit_msg, cwd=path)
    logger.info("Auto-commit: {} ({} files)", commit_msg, len(changed_files))
    return f"[ok] committed {len(changed_files)} file(s): {commit_msg}"


async def auto_commit_tool(message: str | None = None, path: str | None = None) -> str:
    return await auto_commit(path=path, message=message)

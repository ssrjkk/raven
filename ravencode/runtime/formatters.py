"""Auto-formatting — run formatters (ruff/prettier) after file edits."""

from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger

_FORMATTERS: dict[str, list[str]] = {
    ".py": ["ruff", "check", "--fix", "--silent"],
    ".pyi": ["ruff", "check", "--fix", "--silent"],
    ".ts": ["npx", "prettier", "--write"],
    ".tsx": ["npx", "prettier", "--write"],
    ".js": ["npx", "prettier", "--write"],
    ".jsx": ["npx", "prettier", "--write"],
    ".css": ["npx", "prettier", "--write"],
    ".json": ["npx", "prettier", "--write"],
    ".md": ["npx", "prettier", "--write"],
    ".go": ["gofmt", "-l"],
    ".rs": ["rustfmt"],
}


async def _run_formatter(cmd: list[str], path: str) -> str:
    full_cmd = cmd + [path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        return f"[timeout] formatter for {path}"
    except FileNotFoundError:
        return f"[skipped] formatter not found for {path}"
    output = (stdout or b"").decode("utf-8", errors="replace")[:2000]
    if stderr:
        output += "\n" + stderr.decode("utf-8", errors="replace")[:2000]
    if proc.returncode and proc.returncode != 0:
        return f"[format issues] {output.strip()}"
    return output.strip()


async def format_file(path: str) -> str:
    ext = Path(path).suffix.lower()
    cmd = _FORMATTERS.get(ext)
    if cmd is None:
        return ""
    logger.info("Formatting {} with {}", path, cmd[0])
    return await _run_formatter(cmd, path)


async def format_files(paths: list[str]) -> str:
    results = []
    for p in paths:
        result = await format_file(p)
        if result:
            results.append(result)
    return "\n".join(results) if results else "(no formatters applied)"

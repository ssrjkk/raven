from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

_BASH_ALLOWLIST = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "echo",
        "pwd",
        "whoami",
        "date",
        "find",
        "grep",
        "rg",
        "wc",
        "sort",
        "uniq",
        "cut",
        "tr",
        "diff",
        "curl",
        "wget",
        "df",
        "du",
        "free",
        "ps",
        "top",
        "uptime",
        "git",
        "make",
        "npm",
        "pip",
        "go",
        "rustc",
        "cargo",
        "python",
        "python3",
        "node",
        "mkdir",
        "cp",
        "mv",
        "rm",
        "chmod",
        "touch",
        "docker",
        "kubectl",
        "which",
        "type",
        "env",
        "npx",
        "pwsh",
        "powershell",
    }
)




async def bash_exec(command: str, timeout: int = 30) -> str:
    parts = shlex.split(command)
    if not parts:
        return "[error] empty command"
    cmd_base = Path(parts[0]).name
    if cmd_base not in _BASH_ALLOWLIST:
        return f"[denied] command '{cmd_base}' not in allowlist"
    proc = await asyncio.create_subprocess_exec(
        *parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return f"[timeout after {timeout}s]"
    output = (stdout or b"").decode("utf-8", errors="replace")[:30_000]
    if stderr:
        output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:10_000]
    if proc.returncode:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"

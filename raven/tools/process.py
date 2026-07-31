from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def _run_subprocess(args: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), (stderr or b"").decode("utf-8", errors="replace")


async def process_list() -> str:
    if os.name == "nt":
        _rc, stdout, _stderr = await _run_subprocess(["tasklist", "/FO", "CSV", "/NH"])
        lines = stdout.splitlines()[:50]
        return "\n".join(line.strip('"') for line in lines)
    _rc, stdout, _stderr = await _run_subprocess(["ps", "aux", "--sort=-%mem"])
    lines = stdout.splitlines()[:50]
    return "\n".join(lines)


async def process_kill(pid: int) -> str:
    try:
        args = ["taskkill", "/PID", str(pid), "/F"] if sys.platform == "win32" else ["kill", "-TERM", str(pid)]
        rc, _stdout, stderr = await _run_subprocess(args, timeout=10.0)
        if rc != 0:
            stderr_text = stderr.strip()
            return f"Failed to kill process {pid}: {stderr_text or 'unknown error'}"
        return f"Process {pid} terminated"
    except TimeoutError:
        return f"Timeout killing process {pid}"
    except FileNotFoundError:
        return f"Kill command not found for process {pid}"
    except PermissionError:
        return f"Permission denied to kill process {pid}"


def register_process_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="process_list",
            description="List running processes",
            parameters={},
            handler=process_list,
            category="system",
            timeout=15,
        )
    )
    registry.register(
        ToolSpec(
            name="process_kill",
            description="Kill a process by PID",
            parameters={
                "pid": {"type": "integer", "description": "Process ID to kill", "required": True},
            },
            handler=process_kill,
            category="system",
        )
    )

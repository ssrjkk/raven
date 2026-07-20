from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def process_list() -> str:
    if os.name == "nt":
        proc = await asyncio.create_subprocess_exec(
            "tasklist", "/FO", "CSV", "/NH",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        lines = stdout.decode("utf-8", errors="replace").splitlines()[:50]
        return "\n".join(line.strip('"') for line in lines)
    else:
        proc = await asyncio.create_subprocess_exec(
            "ps", "aux", "--sort=-%mem",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        lines = stdout.decode("utf-8", errors="replace").splitlines()[:50]
        return "\n".join(lines)


async def process_kill(pid: int) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *(["taskkill", "/PID", str(pid), "/F"] if sys.platform == "win32" else ["kill", "-TERM", str(pid)]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode != 0:
            stderr_text = stdout.decode("utf-8", errors="replace").strip()
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

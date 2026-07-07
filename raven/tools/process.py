from __future__ import annotations

import asyncio
import subprocess

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def process_list() -> str:
    import os

    if os.name == "nt":
        proc = await asyncio.create_subprocess_exec(
            "tasklist", "/FO", "CSV", "/NH",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode("utf-8", errors="replace").splitlines()[:50]
        return "\n".join(line.strip('"') for line in lines)
    else:
        proc = await asyncio.create_subprocess_exec(
            "ps", "aux", "--sort=-%mem",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode("utf-8", errors="replace").splitlines()[:50]
        return "\n".join(lines)


async def process_kill(pid: int) -> str:
    import signal as sig_mod

    try:
        import os

        os.kill(pid, sig_mod.SIGTERM)
        return f"Process {pid} terminated"
    except ProcessLookupError:
        return f"Process {pid} not found"
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

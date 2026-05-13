from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from raven.core.monitor.models import Monitor


async def check_process(monitor: Monitor) -> dict[str, Any]:
    process_name = monitor.target.strip().lower()
    exact = monitor.config.get("exact_match", True)

    if not process_name:
        return {"error": "No process name specified", "running": False}

    running = await _is_process_running(process_name, exact)

    return {
        "running": running,
        "process": process_name,
        "status": "running" if running else "stopped",
    }


async def _is_process_running(name: str, exact: bool) -> bool:
    import os
    if os.name == "nt":
        proc = await asyncio.create_subprocess_shell(
            f'tasklist /FI "IMAGENAME eq {name}" /NH',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace")
        return name.lower() in output.lower() and "No tasks" not in output
    else:
        if exact:
            proc = await asyncio.create_subprocess_shell(
                f"pgrep -x '{name}'",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                f"pgrep -f '{name}'",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        stdout, _ = await proc.communicate()
        return bool(stdout.decode("utf-8", errors="replace").strip())

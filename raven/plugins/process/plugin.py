from __future__ import annotations

import asyncio
import os
import signal
import sys

from loguru import logger

PLUGIN_NAME = "process"
PLUGIN_DESCRIPTION = "Run, list, and manage system processes"


async def run(command: str, timeout: int = 30) -> str:
    try:
        import shlex
        parts = shlex.split(command)
        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s"

        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            error_text = stderr.decode("utf-8", errors="replace")
            if error_text.strip():
                result += f"\n[stderr]\n{error_text}"
        if proc.returncode is not None and proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        return result[:5000] or "(no output)"
    except Exception as e:
        logger.error("Process run failed: {}", e)
        return f"Error: {e}"


async def run_python(code: str, timeout: int = 15) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s"
        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            error_text = stderr.decode("utf-8", errors="replace")
            if error_text.strip():
                result += f"\n[stderr]\n{error_text}"
        if proc.returncode is not None and proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        return result[:5000] or "(no output)"
    except Exception as e:
        logger.error("Python run failed: {}", e)
        return f"Error: {e}"


async def list_processes(filter: str = "") -> str:
    if sys.platform == "win32":
        proc = await asyncio.create_subprocess_exec(
            "tasklist", "/FO", "CSV", "/NH",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            "ps", "aux", "--sort=-%mem",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        result = stdout.decode("utf-8", errors="replace") if stdout else ""
    except TimeoutError:
        proc.kill()
        return "Command timed out"
    if filter:
        lines = result.split("\n")
        filtered = [line for line in lines if filter.lower() in line.lower()]
        result = "\n".join(filtered) if filtered else f"No processes matching '{filter}'"
    return result


async def kill(pid: int, force: bool = False) -> str:
    try:
        sig = getattr(signal, "SIGKILL", signal.SIGTERM) if force else signal.SIGTERM
        await asyncio.to_thread(os.kill, pid, sig)
        return f"Process {pid} {'forcefully ' if force else ''}terminated"
    except ProcessLookupError:
        return f"Process {pid} not found"
    except PermissionError:
        return f"Permission denied to kill process {pid}"
    except Exception as e:
        logger.error("Kill process {} failed: {}", pid, e)
        return f"Error killing process {pid}: {e}"

from __future__ import annotations
import asyncio
import os
import signal
import sys
from loguru import logger

PLUGIN_NAME = "process"
PLUGIN_DESCRIPTION = "Run, list, and manage system processes"


async def run(command: str, timeout: int = 30, shell: bool = True) -> str:
    """Run a shell command and return output. Args: command (str): Command to execute, timeout (int): Max execution time in seconds, shell (bool): Use shell"""
    try:
        proc = await asyncio.create_subprocess_shell(
            command if shell else command.split(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s"

        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            error_text = stderr.decode("utf-8", errors="replace")
            if error_text.strip():
                result += f"\n[stderr]\n{error_text}"
        if proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        return result[:5000] or "(no output)"
    except Exception as e:
        return f"Error: {e}"


async def run_python(code: str, timeout: int = 15) -> str:
    """Run Python code in a subprocess. Args: code (str): Python code, timeout (int): Max execution time"""
    return await run(f"{sys.executable} -c {_quote(code)}", timeout=timeout, shell=True)


async def list_processes(filter: str = "") -> str:
    """List running processes. Args: filter (str): Optional filter string (e.g. 'python')"""
    if sys.platform == "win32":
        cmd = "tasklist /FO CSV /NH"
    else:
        cmd = "ps aux --sort=-%mem"
    result = await run(cmd, timeout=10)
    if filter:
        lines = result.split("\n")
        filtered = [l for l in lines if filter.lower() in l.lower()]
        result = "\n".join(filtered) if filtered else f"No processes matching '{filter}'"
    return result


async def kill(pid: int, force: bool = False) -> str:
    """Kill a process by PID. Args: pid (int): Process ID, force (bool): Force kill (SIGKILL)"""
    try:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)
        return f"Process {pid} {'forcefully ' if force else ''}terminated"
    except ProcessLookupError:
        return f"Process {pid} not found"
    except PermissionError:
        return f"Permission denied to kill process {pid}"
    except Exception as e:
        return f"Error killing process {pid}: {e}"


def _quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "'\\''")
    return f'"{escaped}"'

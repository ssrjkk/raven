from __future__ import annotations

import asyncio
import os
import platform
import signal
import sys
from pathlib import Path

from loguru import logger

PLUGIN_NAME = "process"
PLUGIN_DESCRIPTION = "Run, list, and manage system processes"

_UNIX_ALLOWLIST = frozenset({
    "ls", "cat", "head", "tail", "echo", "pwd", "whoami", "date",
    "find", "grep", "wc", "sort", "uniq", "cut", "tr", "diff",
    "df", "du", "free", "ps", "top", "uptime", "sleep",
})
_WIN_ALLOWLIST = frozenset({
    "echo", "dir", "type", "cd", "cls", "ver",
    "date", "time", "timeout", "find", "findstr", "sort", "more", "fc",
    "where", "ping", "tracert", "pathping", "nslookup", "tasklist",
    "systeminfo", "ipconfig", "netstat", "whoami",
    "attrib", "mkdir", "rmdir",
})
_ALLOWED = _WIN_ALLOWLIST if platform.system() == "Windows" else _UNIX_ALLOWLIST


async def run(command: str, timeout: int = 30) -> str:
    """Run one allow-listed command in a subprocess and return its stdout, stderr and non-zero exit code.

    command: Command line, split with shlex. Only the first word is checked, and only against the allow list for
        this OS, so anything not listed there is refused without being run.
    timeout: Seconds before the process is killed and the run reported as timed out.
    """
    try:
        import shlex

        parts = shlex.split(command)
        if not parts:
            return "Error: empty command"
        cmd_name = parts[0]
        cmd_base = Path(cmd_name).stem
        if cmd_base not in _ALLOWED:
            return f"Error: '{cmd_name}' is not in the allowed commands list. Allowed: {', '.join(sorted(_ALLOWED))}"
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
        return f"Error: {type(e).__name__}"


async def run_python(code: str, timeout: int = 60) -> str:
    """Run Python code in a separate interpreter and return its stdout, stderr and non-zero exit code.

    code: Module-level source, fed to the runner on stdin. The AST gate refuses dunder access and denied builtins
        as '[denied]' before anything runs; the value of the last expression, if any, is the result.
    timeout: Seconds before the interpreter is killed and the run reported as timed out.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "raven.tools._pyrunner",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=code.encode("utf-8")), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            return f"Code execution timed out after {timeout}s"
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
        return f"Error: {type(e).__name__}"


async def list_processes(filter: str = "") -> str:
    """List the running processes of this machine, sorted by memory use on Unix.

    filter: Keep only the lines containing this text, case-insensitively; empty lists every process. The output is
        one line per process and can be long.
    """
    if sys.platform == "win32":
        proc = await asyncio.create_subprocess_exec(
            "tasklist",
            "/FO",
            "CSV",
            "/NH",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            "ps",
            "aux",
            "--sort=-%mem",
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


def _is_self_or_ancestor(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return True
    if sys.platform != "win32":
        try:
            parent = os.getppid()
            for _ in range(32):
                if parent <= 1:
                    break
                if pid == parent:
                    return True
                with Path(f"/proc/{parent}/stat").open(encoding="utf-8", errors="replace") as f:
                    parent = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            pass
    return False


async def kill(pid: int, force: bool = False) -> str:
    """Send a termination signal to one process by its PID and report what happened.

    pid: Process id to signal. Refusing the gateway's own pid and, on Linux, its ancestors keeps a task from
        killing the process serving it; use list_processes to find the pid first.
    force: Ask for SIGKILL where the platform has it; otherwise SIGTERM, which the process can handle and shut down
        cleanly.
    """
    try:
        if _is_self_or_ancestor(pid):
            return f"Error: refusing to kill process {pid} (gateway or ancestor)"
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

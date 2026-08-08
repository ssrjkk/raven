from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_UNIX_COMMANDS = frozenset(
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
        "wc",
        "sort",
        "uniq",
        "cut",
        "tr",
        "diff",
        "df",
        "du",
        "free",
        "ps",
        "top",
        "uptime",
        "sleep",
    }
)

_WIN_COMMANDS = frozenset(
    {
        "echo",
        "dir",
        "type",
        "copy",
        "del",
        "ren",
        "cd",
        "cls",
        "ver",
        "date",
        "time",
        "timeout",
        "find",
        "findstr",
        "sort",
        "more",
        "fc",
        "where",
        "ping",
        "tracert",
        "pathping",
        "nslookup",
        "tasklist",
        "taskkill",
        "systeminfo",
        "ipconfig",
        "netstat",
        "whoami",
        "set",
        "attrib",
        "xcopy",
        "robocopy",
        "mkdir",
        "rmdir",
    }
)

if platform.system() == "Windows":
    ALLOWED_COMMANDS = _WIN_COMMANDS
else:
    ALLOWED_COMMANDS = _UNIX_COMMANDS

MAX_OUTPUT_CHARS = 30_000
MAX_STDERR_CHARS = 10_000


_FORBIDDEN_EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})


def _validate_command(command: str) -> list[str]:
    import shlex

    parts = shlex.split(command)
    if not parts:
        raise ValueError("empty command")
    base = Path(parts[0]).name if os.path.sep in parts[0] else parts[0]
    if base not in ALLOWED_COMMANDS:
        msg = f"command '{base}' not in allowlist"
        raise ValueError(msg)
    if base == "find":
        for token in parts[1:]:
            if token in _FORBIDDEN_EXEC_FLAGS:
                raise ValueError(f"find flag '{token}' is not allowed")
    return parts


async def shell_command(command: str, timeout: int = 30) -> str:
    try:
        args = _validate_command(command)
    except ValueError as e:
        return f"[denied] {e}"

    _cmd_builtins = {"echo", "dir", "type", "copy", "del", "ren", "cd", "cls", "ver", "date", "time", "set"}
    if platform.system() == "Windows" and args[0].lower() in _cmd_builtins:
        args = ["cmd", "/c", *args]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
        if stderr:
            output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:MAX_STDERR_CHARS]
        if proc.returncode != 0:
            output += f"\n[exit code: {proc.returncode}]"
        return output or "(no output)"
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return f"[timeout after {timeout}s]"


_DENIED_MODULES = frozenset(
    {
        "os",
        "subprocess",
        "sys",
        "shutil",
        "ctypes",
        "socket",
        "operator",
        "inspect",
        "importlib",
        "pickle",
        "marshal",
        "code",
        "codeop",
        "builtins",
        "typing",
    }
)

_RESTRICTED_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "ascii": ascii,
    "bin": bin,
    "bool": bool,
    "bytearray": bytearray,
    "bytes": bytes,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "frozenset": frozenset,
    "hash": hash,
    "hex": hex,
    "int": int,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}

_DENIED_BUILTINS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "type",
        "memoryview",
        "breakpoint",
        "callable",
        "staticmethod",
        "classmethod",
        "property",
        "super",
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "dir",
        "format",
        "format_map",
        "__import__",
        "globals",
        "locals",
    }
)


async def python_code(code: str, timeout: int = 15) -> str:
    try:
        import ast

        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in ("__builtins__", "__import__"):
                return f"[denied] access to '{node.id}' is not allowed"
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.startswith("__")
                and node.value.endswith("__")
            ):
                return f"[denied] dunder string literal '{node.value}' is not allowed"
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in _DENIED_BUILTINS:
                    return f"[denied] use of '{func.id}' is not allowed"
                if isinstance(func, ast.Attribute):
                    if func.attr in _DENIED_BUILTINS:
                        return f"[denied] '{func.attr}' called via attribute access"
                    if isinstance(func.value, ast.Name) and func.value.id in _DENIED_MODULES:
                        return f"[denied] '{func.value.id}' module access is not allowed"
            if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
                return f"[denied] dunder attribute '{node.attr}' is not allowed"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name in _DENIED_MODULES:
                        return f"[denied] import of '{alias.name}' is not allowed"

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "raven.tools._pyrunner",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(code.encode("utf-8")), timeout=timeout)
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            return f"[timeout after {timeout}s]"
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if out:
            return out
        if err:
            logger.warning("Python sandbox subprocess error: {}", err)
            return f"Error: {err}"
        return "(no output)"
    except SyntaxError as e:
        return f"Syntax Error: {e}"
    except Exception as e:
        logger.warning("Python sandbox execution failed: {}", e)
        return f"Error: {e}"


def register_shell_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="shell",
            description="Execute a shell command and return output",
            parameters={
                "command": {"type": "string", "description": "Command to execute", "required": True},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
            },
            handler=shell_command,
            category="system",
            timeout=60,
            dangerous=True,
            allowed_roles=["admin", "developer"],
        )
    )
    registry.register(
        ToolSpec(
            name="python",
            description="Execute Python code and return the result (safe sandbox)",
            parameters={
                "code": {"type": "string", "description": "Python code to execute", "required": True},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
            },
            handler=python_code,
            category="system",
            timeout=30,
            dangerous=True,
            allowed_roles=["admin", "developer"],
        )
    )

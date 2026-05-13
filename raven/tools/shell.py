from __future__ import annotations

import asyncio
import subprocess
import sys

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def shell_command(command: str, timeout: int = 30) -> str:
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = ""
        if stdout:
            output += stdout.decode("utf-8", errors="replace")[:30000]
        if stderr:
            output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:10000]
        if proc.returncode != 0:
            output += f"\n[exit code: {proc.returncode}]"
        return output or "(no output)"
    except asyncio.TimeoutError:
        proc.kill()
        return f"[timeout after {timeout}s]"


async def python_code(code: str, timeout: int = 15) -> str:
    try:
        import ast
        tree = ast.parse(code)
        last_expr = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = tree.body.pop()
        compiled = compile(tree, "<sandbox>", "exec", flags=ast.PyCF_ONLY_AST)
        compiled = compile(compiled, "<sandbox>", "exec")

        ns: dict = {}
        exec(compiled, ns)

        if last_expr:
            compiled_expr = compile(ast.Expression(last_expr.value), "<sandbox>", "eval")
            result = eval(compiled_expr, ns)
            return str(result) if result is not None else "(no return value)"
        return "(code executed, no return value)"
    except Exception as e:
        return f"Error: {e}"


def register_shell_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="shell",
        description="Execute a shell command and return output",
        parameters={
            "command": {"type": "string", "description": "Command to execute", "required": True},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
        },
        handler=shell_command,
        category="system",
        timeout=60,
    ))
    registry.register(ToolSpec(
        name="python",
        description="Execute Python code and return the result (safe sandbox)",
        parameters={
            "code": {"type": "string", "description": "Python code to execute", "required": True},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
        },
        handler=python_code,
        category="system",
        timeout=30,
    ))

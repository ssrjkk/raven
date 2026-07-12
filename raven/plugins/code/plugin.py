from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
from pathlib import Path

from loguru import logger

PLUGIN_NAME = "code"
PLUGIN_DESCRIPTION = "Execute, review, explain, and improve code"

SANDBOX_TIMEOUT = 30


async def run_python(code: str, timeout: int = 30) -> str:
    """Execute Python code in a sandbox and return stdout/stderr. Args: code (str): Python code to execute, timeout (int): Max execution time in seconds"""
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="raven_sandbox_")
        script_path = Path(tmpdir) / "script.py"
        with script_path.open("w", encoding="utf-8") as f:
            f.write(code)

        env = os.environ.copy()
        env.pop("OPENROUTER_API_KEY", None)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        env.pop("TELEGRAM_BOT_TOKEN", None)
        env.pop("DISCORD_BOT_TOKEN", None)
        env.pop("SLACK_BOT_TOKEN", None)
        env.pop("WEB_SECRET_KEY", None)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["http_proxy"] = ""
        env["https_proxy"] = ""

        t = min(timeout, SANDBOX_TIMEOUT)
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=tmpdir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=t)
        except TimeoutError:
            proc.kill()
            return f"Execution timed out after {t}s"

        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            result += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
        if proc.returncode is not None and proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        return result[:3000] or "(no output)"

    except Exception as e:
        logger.error("Code execution failed: {}", e)
        return f"Error: {e}"
    finally:
        if tmpdir and Path(tmpdir).exists():
            import shutil

            with contextlib.suppress(FileNotFoundError, PermissionError, OSError):
                shutil.rmtree(tmpdir)


async def review_code(code: str, language: str = "auto") -> str:
    """Review code for bugs, style issues, and improvements. Args: code (str): Code to review, language (str): Programming language"""
    issues = []
    if len(code) > 500:
        issues.append("⚠️  Function is long (>500 chars); consider breaking it up")
    if "import *" in code:
        issues.append("⚠️  Wildcard imports make it hard to track dependencies")
    if "exec(" in code or "eval(" in code:
        issues.append("🚨  eval/exec detected — security risk")
    if "TODO" in code or "FIXME" in code or "HACK" in code:
        issues.append("📝  Contains TODO/FIXME markers")
    if "print(" in code and "def " in code:
        issues.append("💡  Debug print() found in function — remove before production")
    if "password" in code.lower() or "secret" in code.lower() or "token" in code.lower():
        issues.append("🚨  Possible hardcoded secret detected")

    if not issues:
        issues.append("✅ No obvious issues found (basic scan)")
    return f"## Code Review — {language}\n\n" + "\n".join(issues) + f"\n\n```\n{code[:1500]}\n```"


async def suggest_edit(code: str, goal: str) -> str:
    """Suggest an edit to achieve a goal. Args: code (str): Original code, goal (str): What the edit should achieve"""
    import ast

    hints = []
    try:
        tree = ast.parse(code)
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]

        hints.append(f"• {len(funcs)} function(s), {len(classes)} class(es), {len(imports)} import(s)")
        if calls:
            hints.append(f"• {len(calls)} call(s) — check for proper error handling")

        if goal.lower() in ("optimize", "perf", "speed"):
            hints.append("• Profile with cProfile to find bottlenecks")
            hints.append("• Replace loops with comprehensions / built-ins")
            hints.append("• Add `@lru_cache` on pure functions")
        elif goal.lower() in ("read", "readability", "clean"):
            hints.append("• Break large functions into smaller ones")
            hints.append("• Add type hints and docstrings")
            hints.append("• Extract magic numbers into named constants")
        elif goal.lower() in ("test", "tests", "unittest"):
            hints.append("• Add `pytest` tests covering edge cases")
            hints.append("• Mock external dependencies")
            hints.append("• Test both success and failure paths")
        elif goal.lower() in ("security", "secure", "safe"):
            hints.append("• Audit all `eval()` / `exec()` calls")
            hints.append("• Validate untrusted input")
            hints.append("• Use parameterized queries for databases")
    except SyntaxError as e:
        hints.append(f"• Parse error: {e}")

    return (
        f"## Suggested Edit\n\n"
        f"**Goal:** {goal}\n\n"
        f"**Code Analysis:**\n"
        + "\n".join(hints)
        + f"\n\n**Current code:**\n```\n{code[:1500]}\n```\n"
    )


async def explain_code(code: str, detail: str = "high") -> str:
    """Explain what code does. Args: code (str): Code to explain, detail (str): 'high' for overview or 'low' for line-by-line"""
    import ast

    lines = code.split("\n")
    overview_parts = [f"**{len(lines)} lines, ~{len(code)} chars**"]

    try:
        tree = ast.parse(code)
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        top_level = [n for n in ast.iter_child_nodes(tree)]

        if classes:
            overview_parts.append(f"**Classes:** {', '.join(c.name for c in classes[:5])}")
        if funcs:
            overview_parts.append(f"**Functions:** {', '.join(f.name for f in funcs[:8])}")
        for node in top_level:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        overview_parts.append(f"**Constant:** {t.id}")
        overview_parts.append(f"**Structure:** {len(top_level)} top-level statement(s)")
    except SyntaxError as e:
        overview_parts.append(f"*Parse error: {e}*")

    section = ""
    if detail == "low":
        annotated = []
        for i, line in enumerate(lines[:40], 1):
            stripped = line.strip()
            if stripped:
                annotated.append(f"`{i:2d}` | {stripped[:120]}")
        section = "\n".join(annotated) if annotated else "(empty)"
    else:
        section = "\n".join(overview_parts)

    return f"## Code Explanation ({detail} level)\n\n{section}\n\n```\n{code[:2000]}\n```"


async def find_issues(code: str) -> str:
    """Find potential bugs, vulnerabilities, and anti-patterns. Args: code (str): Code to analyze"""
    import ast

    issues = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("eval", "exec", "compile"):
                    issues.append(f"Line {node.lineno}: Dangerous dynamic code execution")
                if (
                    node.func.attr == "input"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "builtins"
                ):
                    issues.append(f"Line {node.lineno}: Unsafe input() — use with caution")
            if isinstance(node, ast.Try) and len(node.handlers) == 1:
                h = node.handlers[0]
                if h.type is None:
                    issues.append(f"Line {h.lineno}: Bare except — catches all exceptions silently")
    except SyntaxError as e:
        issues.append(f"Parse error: {e}")

    if not issues:
        issues.append("✅ No AST-level issues found")
    return "## Issue Scan\n\n" + "\n".join(issues)

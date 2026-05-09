from __future__ import annotations
import asyncio
import os
import tempfile
import sys
import json
from pathlib import Path
from loguru import logger

PLUGIN_NAME = "code"
PLUGIN_DESCRIPTION = "Execute Python code in a sandboxed environment"

SANDBOX_TIMEOUT = 30


async def run_python(code: str, timeout: int = 30) -> str:
    """Execute Python code in a sandbox and return stdout/stderr. Args: code (str): Python code to execute, timeout (int): Max execution time in seconds"""
    tmpdir = None
    try:
        tmpdir = tempfile.mkdtemp(prefix="raven_sandbox_")
        script_path = os.path.join(tmpdir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
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
            sys.executable, script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=tmpdir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=t)
        except asyncio.TimeoutError:
            proc.kill()
            return f"Execution timed out after {t}s"

        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            result += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        return result[:3000] or "(no output)"

    except Exception as e:
        logger.error("Code execution failed: {}", e)
        return f"Error: {e}"
    finally:
        if tmpdir and os.path.exists(tmpdir):
            import shutil
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass

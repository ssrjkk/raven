import asyncio
import subprocess
import sys
from typing import Any

from loguru import logger

from raven.core.config import settings
from raven.core.rag.retriever import Retriever
from raven.plugins.files import plugin as files_plugin

_ALLOWED_COMMANDS = frozenset(
    {
        "ls",
        "cat",
        "echo",
        "pwd",
        "cd",
        "mkdir",
        "rm",
        "cp",
        "mv",
        "grep",
        "find",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        "diff",
        "python",
        "node",
        "npm",
        "npx",
        "git",
        "pip",
        "curl",
        "wget",
        "docker",
    }
)

_SHELL_META = set("&|;<>^()")


class RuntimeAdapter:
    @staticmethod
    async def run_command(cmd: str) -> str:
        import shlex

        parts = shlex.split(cmd)
        if parts and parts[0] not in _ALLOWED_COMMANDS:
            return f"Command not allowed: {parts[0]}"
        if sys.platform == "win32":
            for token in parts:
                if any(c in _SHELL_META for c in token):
                    return "Command not allowed: shell operators are forbidden on Windows"
            proc = await asyncio.create_subprocess_exec(
                "cmd.exe",
                "/c",
                *parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except TimeoutError:
            proc.kill()
            return "Command timed out after 120s"
        return stdout.decode(errors="replace") + stderr.decode(errors="replace")

    @staticmethod
    async def read_file(path: str) -> str:
        try:
            return await files_plugin.read(path)
        except Exception as exc:
            logger.error("Failed to read {}: {}", path, exc)
            return "Read error"

    @staticmethod
    async def write_file(path: str, content: str) -> str:
        try:
            return await files_plugin.write(path, content)
        except Exception as exc:
            logger.error("Failed to write {}: {}", path, exc)
            return "Write error"

    @staticmethod
    async def create_sandbox(image: str = "python:3.12") -> dict[str, Any]:
        from raven.core.sandbox import Sandbox, SandboxConfig

        config = SandboxConfig(mode="subprocess", docker_image=image)
        sandbox = Sandbox(config)
        return {"sandbox": sandbox, "mode": config.mode, "image": image}

    @staticmethod
    async def search_codebase(query: str, path: str | None = None) -> list[str]:
        try:
            db_path = settings.resolved_db_path
        except AttributeError:
            from pathlib import Path

            db_path = Path("data/rag")
        retriever = Retriever(db_path=str(db_path))
        results = await retriever.retrieve(query, k=5)
        return [r.get("text", str(r)) for r in results]

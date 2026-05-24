"""Shell execution and filesystem operations."""

from __future__ import annotations

import asyncio
import subprocess

from loguru import logger

from raven.plugins.files import plugin as files_plugin
from raven.core.rag.retriever import Retriever
from raven.core.config import settings


class ShellExecutor:
    """Safe shell command execution with timeout and error handling."""

    DEFAULT_TIMEOUT = 120

    async def run(self, cmd: str, timeout: int | None = None) -> str:
        timeout = timeout or self.DEFAULT_TIMEOUT
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            logger.warning("Command timed out after {}s: {}", timeout, cmd)
            return f"Command timed out after {timeout}s"
        except Exception as exc:
            logger.error("Command execution failed: {}", exc)
            return f"Execution error: {exc}"

        output = stdout.decode(errors="replace")
        error = stderr.decode(errors="replace")
        return output + error

    async def read_file(self, path: str) -> str:
        try:
            return await files_plugin.read(path)
        except Exception as exc:
            logger.error("Failed to read file {}: {}", path, exc)
            return f"Error reading {path}: {exc}"

    async def write_file(self, path: str, content: str) -> str:
        try:
            return await files_plugin.write(path, content)
        except Exception as exc:
            logger.error("Failed to write file {}: {}", path, exc)
            return f"Error writing {path}: {exc}"

    async def search_codebase(self, query: str, k: int = 5) -> list[str]:
        try:
            db_path = str(settings.resolved_db_path) if hasattr(settings, "resolved_db_path") else "data/rag"
            retriever = Retriever(db_path=db_path)
            results = await retriever.retrieve(query, k=k)
            return [r.get("text", str(r)) for r in results]
        except Exception as exc:
            logger.error("Search failed: {}", exc)
            return [f"Search error: {exc}"]

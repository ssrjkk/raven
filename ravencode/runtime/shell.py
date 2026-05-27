"""Shell execution and filesystem operations."""

from __future__ import annotations

import asyncio
import subprocess

from loguru import logger


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
            raise TimeoutError(f"Command timed out after {timeout}s")
        except Exception as exc:
            logger.error("Command execution failed: {}", exc)
            raise

        output = stdout.decode(errors="replace")
        error = stderr.decode(errors="replace")
        return output + error

    async def read_file(self, path: str) -> str:
        from raven.plugins.files import plugin as files_plugin

        try:
            return await files_plugin.read(path)
        except Exception as exc:
            logger.error("Failed to read file {}: {}", path, exc)
            raise

    async def write_file(self, path: str, content: str) -> str:
        from raven.plugins.files import plugin as files_plugin

        try:
            return await files_plugin.write(path, content)
        except Exception as exc:
            logger.error("Failed to write file {}: {}", path, exc)
            raise

    async def search_codebase(self, query: str, k: int = 5) -> list[str]:
        from raven.core.rag.retriever import Retriever
        from raven.core.config import settings

        try:
            db_path = settings.resolved_db_path
        except AttributeError:
            from pathlib import Path
            db_path = Path("data/rag")
        try:
            retriever = Retriever(db_path=str(db_path))
            results = await retriever.retrieve(query, k=k)
            return [r.get("text", str(r)) for r in results]
        except Exception as exc:
            logger.error("Search failed: {}", exc)
            raise

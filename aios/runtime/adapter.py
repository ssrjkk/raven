"""
Runtime Adapter — connects Raven's Python runtime with the
TypeScript runtime layer (terminal, fs, docker).

Provides a unified interface for both Python and TS code execution.
"""

import asyncio
import subprocess
from typing import Any


class RuntimeAdapter:
    """Unified runtime for command execution, filesystem ops, and sandboxing."""

    @staticmethod
    async def run_command(cmd: str, shell: bool = True) -> str:
        """Execute a shell command — used by both Python and TS subsystems."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode() + stderr.decode()
        return output

    @staticmethod
    async def read_file(path: str) -> str:
        """Read a file from the filesystem."""
        from raven.plugins.files.plugin import FilePlugin
        plugin = FilePlugin()
        return await plugin.read(path)

    @staticmethod
    async def write_file(path: str, content: str) -> None:
        """Write content to a file."""
        from raven.plugins.files.plugin import FilePlugin
        plugin = FilePlugin()
        await plugin.write(path, content)

    @staticmethod
    async def create_sandbox(image: str = "python:3.12") -> dict[str, Any]:
        """Create a sandboxed execution environment."""
        from raven.core.sandbox import Sandbox
        sandbox = Sandbox()
        return await sandbox.create(image=image)

    @staticmethod
    async def search_codebase(query: str, path: str | None = None) -> list[str]:
        """Semantic search across the codebase."""
        from raven.core.rag.retriever import Retriever
        retriever = Retriever()
        results = await retriever.search(query, path=path)
        return [r.content for r in results]

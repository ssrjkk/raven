"""
Runtime Adapter — unified interface for Raven's Python runtime.

Provides command execution, filesystem ops, sandboxing, and search.
"""

import asyncio
import subprocess
from typing import Any
from raven.core.config import settings
from raven.plugins.files import plugin as files_plugin
from raven.core.rag.retriever import Retriever


class RuntimeAdapter:
    """Unified runtime for command execution, filesystem, and sandboxing."""

    @staticmethod
    async def run_command(cmd: str, shell: bool = True) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            return "Command timed out after 120s"
        output = stdout.decode() + stderr.decode()
        return output

    @staticmethod
    async def read_file(path: str) -> str:
        return await files_plugin.read(path)

    @staticmethod
    async def write_file(path: str, content: str) -> str:
        return await files_plugin.write(path, content)

    @staticmethod
    async def create_sandbox(image: str = "python:3.12") -> dict[str, Any]:
        from raven.core.sandbox import Sandbox, SandboxConfig
        config = SandboxConfig(mode="subprocess", docker_image=image)
        sandbox = Sandbox(config)
        return {"sandbox": sandbox, "mode": config.mode, "image": image}

    @staticmethod
    async def search_codebase(query: str, path: str | None = None) -> list[str]:
        db_path = str(settings.resolved_db_path) if hasattr(settings, 'resolved_db_path') else "data/rag"
        retriever = Retriever(db_path=db_path)
        results = await retriever.retrieve(query, k=5)
        return [r.get("text", str(r)) for r in results]

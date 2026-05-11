from __future__ import annotations
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from loguru import logger


SANDBOX_IMAGE = "python:3.12-slim"


class SandboxConfig:
    def __init__(
        self,
        mode: str = "none",
        allow_network: bool = False,
        allow_read: list[str] | None = None,
        allow_write: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        denied_tools: list[str] | None = None,
        timeout: int = 30,
        docker_image: str = SANDBOX_IMAGE,
    ):
        self.mode = mode
        self.allow_network = allow_network
        self.allow_read = allow_read or []
        self.allow_write = allow_write or []
        self.allowed_tools = allowed_tools
        self.denied_tools = denied_tools or []
        self.timeout = timeout
        self.docker_image = docker_image


DEFAULT_SANDBOX = SandboxConfig(
    mode="none",
    denied_tools=[],
)


class Sandbox:
    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or DEFAULT_SANDBOX
        self._tmpdir: str | None = None

    async def exec(self, code: str, tool_name: str = "") -> str:
        if self.config.denied_tools and tool_name in self.config.denied_tools:
            return f"Tool '{tool_name}' is denied in current sandbox"
        if self.config.allowed_tools and tool_name and tool_name not in self.config.allowed_tools:
            return f"Tool '{tool_name}' is not allowed in current sandbox"

        if self.config.mode == "none":
            return await self._exec_direct(code)
        elif self.config.mode == "subprocess":
            return await self._exec_subprocess(code)
        elif self.config.mode == "docker":
            return await self._exec_docker(code)
        return "Unknown sandbox mode"

    async def _exec_direct(self, code: str) -> str:
        return code

    async def _exec_subprocess(self, code: str) -> str:
        self._tmpdir = tempfile.mkdtemp(prefix="raven_sandbox_")
        script = os.path.join(self._tmpdir, "script.py")
        with open(script, "w") as f:
            f.write(code)
        env = os.environ.copy()
        if not self.config.allow_network:
            for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                env.pop(key, None)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self._tmpdir,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.config.timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return "Execution timed out"
        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            err = stderr.decode("utf-8", errors="replace")
            if err.strip():
                result += f"\n[stderr]\n{err}"
        return result[:5000] or "(no output)"

    async def _exec_docker(self, code: str) -> str:
        try:
            import docker
        except ImportError:
            return "Docker sandbox requires 'docker' Python package: pip install docker"

        try:
            client = docker.from_env()
            await asyncio.sleep(0)
        except Exception as e:
            return f"Docker not available: {e}"

        self._tmpdir = tempfile.mkdtemp(prefix="raven_sandbox_")
        script_path = os.path.join(self._tmpdir, "script.py")
        with open(script_path, "w") as f:
            f.write(code)

        container = None
        try:
            container = client.containers.create(
                image=self.config.docker_image,
                command=["python", "/sandbox/script.py"],
                working_dir="/sandbox",
                volumes={self._tmpdir: {"bind": "/sandbox", "mode": "ro"}},
                network_disabled=not self.config.allow_network,
                read_only=True,
                mem_limit="256m",
                cpu_period=100000,
                cpu_quota=50000,
                pids_limit=64,
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, container.start)
            exit_code = await loop.run_in_executor(
                None,
                lambda: container.wait(timeout=self.config.timeout).get("StatusCode", -1),
            )
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
            return logs[:5000] or f"(exit code {exit_code})"
        except Exception as e:
            return f"Docker execution error: {e}"
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    async def cleanup(self):
        if self._tmpdir:
            import shutil
            try:
                shutil.rmtree(self._tmpdir)
            except Exception:
                pass
            self._tmpdir = None


sandbox_default = Sandbox()

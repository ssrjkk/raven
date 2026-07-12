from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

SANDBOX_IMAGE = "python:3.12-slim"

ALLOW_ALL_NETWORK = {"allow": ["*"]}
DENY_ALL_NETWORK = {"allow": [], "deny": ["*"]}


class SandboxConfig:
    def __init__(
        self,
        mode: str = "subprocess",
        allow_network: bool = False,
        allow_read: list[str] | None = None,
        allow_write: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        denied_tools: list[str] | None = None,
        timeout: int = 30,
        docker_image: str = SANDBOX_IMAGE,
        network_rules: dict[str, Any] | None = None,
    ):
        self.mode = mode
        self.allow_network = allow_network
        self.allow_read = allow_read or []
        self.allow_write = allow_write or []
        self.allowed_tools = allowed_tools
        self.denied_tools = denied_tools or []
        self.timeout = timeout
        self.docker_image = docker_image
        self.network_rules = network_rules

    @property
    def effective_network_rules(self) -> dict[str, Any]:
        if self.network_rules is not None:
            return self.network_rules
        if not self.allow_network:
            return DENY_ALL_NETWORK
        return ALLOW_ALL_NETWORK


DEFAULT_SANDBOX = SandboxConfig(
    mode="subprocess",
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
        script = Path(self._tmpdir) / "script.py"
        with script.open("w") as f:
            f.write(code)
        env = os.environ.copy()

        net_rules = self.config.effective_network_rules
        allow_list = net_rules.get("allow", [])
        has_selective_allow = allow_list and allow_list != ["*"]

        if has_selective_allow:
            env["RAVEN_NET_ALLOW"] = ",".join(allow_list)
        elif not self.config.allow_network:
            for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
                env.pop(key, None)
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self._tmpdir,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.config.timeout)
        except TimeoutError:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                logger.debug("Process already exited during kill")
            return "Execution timed out"
        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            err = stderr.decode("utf-8", errors="replace")
            if err.strip():
                result += f"\n[stderr]\n{err}"
        return result[:5000] or "(no output)"

    def _build_net_allow_entrypoint(self) -> str | None:
        rules = self.config.effective_network_rules
        allow = rules.get("allow", [])
        deny = rules.get("deny", [])
        if not allow:
            return None
        if allow == ["*"] and not deny:
            return None
        parts = ["#!/bin/sh", "set -e"]
        parts.append("iptables -F OUTPUT")
        parts.append("iptables -P OUTPUT DROP")
        parts.append("iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT")
        parts.append("iptables -A OUTPUT -o lo -j ACCEPT")
        for domain in allow:
            if domain == "*":
                parts.append("iptables -P OUTPUT ACCEPT")
                parts.append("iptables -F OUTPUT")
                return "\n".join(parts)
            parts.append(f"iptables -A OUTPUT -d {domain} -j ACCEPT")
        for domain in deny:
            if domain == "*":
                continue
            parts.append(f"iptables -A OUTPUT -d {domain} -j DROP")
        parts.append("exec \"$@\"")
        return "\n".join(parts)

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
        script_path = Path(self._tmpdir) / "script.py"
        with script_path.open("w") as f:
            f.write(code)

        net_rules = self.config.effective_network_rules
        allow_list = net_rules.get("allow", [])
        has_selective_allow = allow_list and allow_list != ["*"]
        net_entrypoint = self._build_net_allow_entrypoint() if has_selective_allow else None

        container_kwargs: dict[str, Any] = {
            "image": self.config.docker_image,
            "command": ["python", "/sandbox/script.py"],
            "working_dir": "/sandbox",
            "volumes": {self._tmpdir: {"bind": "/sandbox", "mode": "ro"}},
            "read_only": True,
            "mem_limit": "256m",
            "cpu_period": 100000,
            "cpu_quota": 50000,
            "pids_limit": 64,
        }

        if net_entrypoint:
            entrypoint_path = Path(self._tmpdir) / "entrypoint.sh"
            entrypoint_path.write_text(net_entrypoint)
            entrypoint_path.chmod(0o755)
            container_kwargs["volumes"][self._tmpdir] = {"bind": "/sandbox", "mode": "ro"}
            container_kwargs["entrypoint"] = ["/bin/sh", "/sandbox/entrypoint.sh"]
            container_kwargs["command"] = ["python", "/sandbox/script.py"]
            container_kwargs["cap_add"] = ["NET_ADMIN", "NET_RAW"]
            container_kwargs["network_disabled"] = False
        else:
            container_kwargs["network_disabled"] = not self.config.allow_network

        container = None
        try:
            container = client.containers.create(**container_kwargs)
            loop = asyncio.get_running_loop()
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
                except (docker.errors.DockerException, docker.errors.NotFound):
                    logger.debug("Container already removed or Docker error during cleanup")

    async def cleanup(self):
        if self._tmpdir:
            import shutil

            try:
                shutil.rmtree(self._tmpdir)
            except (FileNotFoundError, PermissionError, OSError) as exc:
                logger.debug("Failed to remove temp dir: {}", exc)
            self._tmpdir = None


sandbox_default = Sandbox()

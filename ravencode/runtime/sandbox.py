from __future__ import annotations

import asyncio
import shlex
import tempfile
from pathlib import Path


class Sandbox:
    def __init__(self, image: str = "python:3.11-slim", timeout: int = 30) -> None:
        self.image = image
        self.timeout = timeout

    async def run_code(self, code: str, language: str = "python") -> str:
        if language == "python":
            return await self._run_python(code)
        return await self._run_custom(code, language)

    async def _run_python(self, code: str) -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "script.py"
            script.write_text(code, encoding="utf-8")
            return await self._docker_exec(
                ["python", "/workspace/script.py"],
                volumes={tmpdir: {"bind": "/workspace", "mode": "ro"}},
            )

    async def _run_custom(self, code: str, language: str) -> str:
        ext_map = {"python": ".py", "javascript": ".js", "typescript": ".ts", "go": ".go", "rust": ".rs", "bash": ".sh"}
        ext = ext_map.get(language, ".txt")
        cmd_map = {
            "python": ["python", f"/workspace/code{ext}"],
            "javascript": ["node", f"/workspace/code{ext}"],
            "bash": ["bash", f"/workspace/code{ext}"],
        }
        cmd = cmd_map.get(language, ["python", f"/workspace/code{ext}"])
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / f"code{ext}"
            script.write_text(code, encoding="utf-8")
            return await self._docker_exec(cmd, volumes={tmpdir: {"bind": "/workspace", "mode": "ro"}})

    async def run_command(self, command: str) -> str:
        parts = shlex.split(command)
        return await self._docker_exec(parts)

    async def _docker_exec(self, cmd: list[str], volumes: dict[str, dict[str, str]] | None = None) -> str:
        docker_cmd = ["docker", "run", "--rm", "-i"]
        if volumes:
            for host, cfg in volumes.items():
                docker_cmd.extend(["-v", f"{host}:{cfg['bind']}:{cfg['mode']}"])
        docker_cmd.extend([self.image] + cmd)
        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except TimeoutError:
            return f"[sandbox timeout after {self.timeout}s]"
        output = (stdout or b"").decode("utf-8", errors="replace")[:30_000]
        if stderr:
            output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:10_000]
        if proc.returncode:
            output += f"\n[exit code: {proc.returncode}]"
        return output or "(no output)"


_sandbox: Sandbox | None = None


def get_sandbox(image: str = "python:3.11-slim") -> Sandbox:
    global _sandbox
    if _sandbox is None:
        _sandbox = Sandbox(image=image)
    return _sandbox


async def sandbox_exec(code: str, language: str = "python") -> str:
    return await get_sandbox().run_code(code, language)

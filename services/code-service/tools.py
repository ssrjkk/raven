from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any


class Tool:
    async def execute(self, **kwargs: Any) -> str:
        raise NotImplementedError


class ReadFileTool(Tool):
    async def execute(self, path: str, max_chars: int = 50000) -> str:
        p = Path(path).resolve()
        if not p.is_file():
            return f"[error] file not found: {path}"
        try:
            content = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n... (truncated, {len(content)} total chars)"
            return content
        except Exception as exc:
            return f"[error] cannot read {path}: {exc}"


class WriteFileTool(Tool):
    async def execute(self, path: str, content: str) -> str:
        p = Path(path).resolve()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(p.write_text, content, encoding="utf-8")
            return f"[ok] wrote {len(content)} chars to {path}"
        except Exception as exc:
            return f"[error] cannot write {path}: {exc}"


class EditFileTool(Tool):
    async def execute(self, path: str, old_string: str, new_string: str) -> str:
        p = Path(path).resolve()
        if not p.is_file():
            return f"[error] file not found: {path}"
        try:
            content = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
            if old_string not in content:
                return f"[error] old_string not found in {path}"
            count = content.count(old_string)
            if count > 1:
                return f"[error] found {count} occurrences — provide more context"
            new_content = content.replace(old_string, new_string, 1)
            await asyncio.to_thread(p.write_text, new_content, encoding="utf-8")
            return f"[ok] applied edit to {path}"
        except Exception as exc:
            return f"[error] edit failed: {exc}"


class BashTool(Tool):
    async def execute(self, command: str, timeout: int = 30) -> str:
        parts = shlex.split(command)
        if not parts:
            return "[error] empty command"
        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return f"[timeout after {timeout}s]"
        output = (stdout or b"").decode("utf-8", errors="replace")[:30000]
        if stderr:
            output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:5000]
        if proc.returncode:
            output += f"\n[exit code: {proc.returncode}]"
        return output or "(no output)"


class SearchTool(Tool):
    async def execute(self, query: str, path: str | None = None, type: str = "text") -> str:
        search_root = Path(path or ".").resolve()
        if not search_root.is_dir():
            return f"[error] directory not found: {path or '.'}"
        results: list[str] = []
        for p in search_root.rglob("*"):
            if not p.is_file():
                continue
            try:
                text = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if query in line:
                    rel = str(p.relative_to(search_root))
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 100:
                        break
            if len(results) >= 100:
                break
        if not results:
            return "(no matches)"
        return "\n".join(results[:100])


class GlobTool(Tool):
    async def execute(self, pattern: str, path: str | None = None) -> str:
        search_root = Path(path or ".").resolve()
        if not search_root.is_dir():
            return f"[error] directory not found: {path or '.'}"
        import fnmatch
        results = []
        for p in search_root.rglob("*"):
            if p.is_file() and fnmatch.fnmatch(p.name, pattern):
                results.append(str(p.relative_to(search_root)))
                if len(results) >= 200:
                    break
        if not results:
            return "(no files match)"
        return "\n".join(sorted(results)[:200])


class GrepTool(Tool):
    async def execute(self, pattern: str, include: str | None = None, path: str | None = None) -> str:
        search_root = Path(path or ".").resolve()
        if not search_root.is_dir():
            return f"[error] directory not found: {path or '.'}"
        import fnmatch
        results = []
        for p in search_root.rglob("*"):
            if not p.is_file():
                continue
            if include and not fnmatch.fnmatch(p.name, include):
                continue
            try:
                text = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern in line:
                    rel = str(p.relative_to(search_root))
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 200:
                        break
            if len(results) >= 200:
                break
        if not results:
            return "(no matches)"
        return "\n".join(results[:200])


class ToolDelegateTool(Tool):
    async def execute(self, description: str, context: str | None = None) -> str:
        from services.code-service.agent import AgentMode, RavenCodeAgent
        sub = RavenCodeAgent(mode=AgentMode.GENERAL, workspace=".")
        prompt = f"{context}\n\n{description}" if context else description
        return await sub.run(prompt)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {
            "read_file": ReadFileTool(),
            "write_file": WriteFileTool(),
            "edit_file": EditFileTool(),
            "bash": BashTool(),
            "search": SearchTool(),
            "glob": GlobTool(),
            "grep": GrepTool(),
            "tool_delegate": ToolDelegateTool(),
        }

    def execute(self, name: str, **kwargs: Any) -> str:
        tool = self._tools.get(name)
        if not tool:
            return f"[error] unknown tool: {name}"
        return tool.execute(**kwargs)

    def list(self) -> list[str]:
        return list(self._tools.keys())

    def for_mode(self, mode: str) -> list[str]:
        from services.code-service.agent import AgentMode, _MODE_TOOLS
        return _MODE_TOOLS.get(AgentMode(mode), ["read_file", "search"])

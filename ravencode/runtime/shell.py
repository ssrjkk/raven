from __future__ import annotations

import asyncio
import fnmatch
import shlex
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger


class ShellExecutor:
    """Safe shell command execution with timeout and error handling."""

    DEFAULT_TIMEOUT = 120

    async def run(self, cmd: str, timeout: int | None = None) -> str:
        timeout = timeout or self.DEFAULT_TIMEOUT
        parts = shlex.split(cmd)
        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            logger.warning("Command timed out after {}s: {}", timeout, cmd)
            raise TimeoutError(f"Command timed out after {timeout}s") from None
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

    async def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            return f"[error] file not found: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")
        if old_string not in content:
            return f"[error] old_string not found in {path}"
        count = content.count(old_string)
        if count > 1:
            return f"[error] found {count} occurrences — provide more context"
        p.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"[ok] edited {path}"

    async def glob_files(self, pattern: str, path: str | None = None) -> list[str]:
        search_root = Path(path).expanduser().resolve() if path else Path.cwd()
        if not search_root.is_dir():
            return [f"[error] not a directory: {search_root}"]
        results = []
        for p in search_root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(search_root)
                if fnmatch.fnmatch(str(rel), pattern):
                    results.append(str(rel))
        return sorted(results)[:500]

    async def grep_files(self, pattern: str, include: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
        search_root = Path(path).expanduser().resolve() if path else Path.cwd()
        if not search_root.is_dir():
            return [{"error": f"not a directory: {search_root}"}]
        results = []
        for p in search_root.rglob("*"):
            if not p.is_file():
                continue
            if include and not fnmatch.fnmatch(p.name, include):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                logger.debug("Skipping unreadable file: {}", p)
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern in line:
                    results.append({
                        "file": str(p.relative_to(search_root)),
                        "line": i,
                        "content": line[:200],
                    })
                    if len(results) >= 200:
                        return results
        return results

    async def search_codebase(self, query: str, k: int = 5) -> list[str]:
        from pathlib import Path as _Path

        from raven.core.config import settings
        from raven.core.rag.retriever import Retriever
        try:
            db_path = str(settings.resolved_db_path)
        except AttributeError:
            db_path = str(_Path("data/rag"))
        try:
            retriever = Retriever(db_path=db_path)
            results = await retriever.retrieve(query, k=k)
            return [r.get("text", str(r)) for r in results]
        except Exception as exc:
            logger.error("Search failed: {}", exc)
            raise

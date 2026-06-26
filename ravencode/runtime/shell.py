from __future__ import annotations

from typing import Any

from ravencode.runtime.tools import (
    bash_exec,
    edit_file,
    glob_files,
    grep_files,
    read_file,
    write_file,
)


class ShellExecutor:
    """Safe shell command execution delegating to confined tools."""

    DEFAULT_TIMEOUT = 120

    async def run(self, cmd: str, timeout: int | None = None) -> str:
        return await bash_exec(command=cmd, timeout=timeout or self.DEFAULT_TIMEOUT)

    async def read_file(self, path: str) -> str:
        return await read_file(path=path)

    async def write_file(self, path: str, content: str) -> str:
        return await write_file(path=path, content=content)

    async def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        return await edit_file(path=path, old_string=old_string, new_string=new_string, preview=False)

    async def glob_files(self, pattern: str, path: str | None = None) -> list[str]:
        return await glob_files(pattern=pattern, path=path)

    async def grep_files(self, pattern: str, include: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
        return await grep_files(pattern=pattern, include=include, path=path)

from __future__ import annotations

from pathlib import Path


class CodebaseContext:
    def __init__(self, workspace: str = ".") -> None:
        self.workspace = Path(workspace).resolve()

    async def index_codebase(self) -> dict:
        return {"files": 0, "chunks": 0, "status": "stub"}

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        return []

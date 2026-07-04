from __future__ import annotations

import asyncio
from pathlib import Path

from loguru import logger


class CodebaseContext:
    def __init__(self, workspace: str = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self._index: dict[str, list[dict]] = {}

    async def index_codebase(self) -> dict:
        files_indexed = 0
        chunks = 0
        ext_map = {".py": "python", ".js": "javascript", ".ts": "typescript", ".rs": "rust", ".go": "go", ".java": "java", ".cpp": "cpp", ".h": "c"}
        for p in self.workspace.rglob("*"):
            if not p.is_file() or p.suffix not in ext_map:
                continue
            if any(part.startswith(".") or part == "node_modules" or part == "__pycache__" for part in p.relative_to(self.workspace).parts):
                continue
            try:
                text = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("Skipping unreadable {}: {}", p, e)
                continue
            chunks += max(1, len(text) // 1000)
            files_indexed += 1
            self._index.setdefault(ext_map.get(p.suffix, "unknown"), []).append({"path": str(p.relative_to(self.workspace)), "text": text[:50000], "size": len(text)})
        logger.info("Indexed {} files, {} chunks from {}", files_indexed, chunks, self.workspace)
        return {"files": files_indexed, "chunks": chunks, "status": "indexed"}

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._index:
            return []
        query_lower = query.lower()
        results: list[dict] = []
        for lang, files in self._index.items():
            for f in files:
                score = 0
                text_lower = f["text"].lower()
                score += text_lower.count(query_lower) * 10
                for word in query_lower.split():
                    if word in f["path"].lower():
                        score += 5
                if score > 0:
                    lines = f["text"].splitlines()
                    context_lines = [ln.strip() for ln in lines if query_lower in ln.lower()][:5]
                    results.append({"file": f["path"], "language": lang, "score": score, "content": "\n".join(context_lines) if context_lines else f["text"][:500]})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

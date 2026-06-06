from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger


class DocumentChunker:
    def __init__(self, chunk_size: int = 512, overlap: int = 64):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str, source: str = "", metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]
            if end < len(text):
                break_at = chunk_text.rfind("\n\n")
                if break_at != -1 and break_at > self.chunk_size // 2:
                    chunk_text = chunk_text[:break_at]
                    end = start + break_at
            chunks.append(
                {
                    "text": chunk_text.strip(),
                    "source": source,
                    "chunk_start": start,
                    "chunk_end": end,
                    **(metadata or {}),
                }
            )
            if end >= len(text):
                break
            next_start = end - self.overlap
            if next_start <= start:
                next_start = end
            start = next_start
        return chunks

    def chunk_file(self, file_path: str | Path, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        p = Path(file_path)
        if not p.is_file():
            logger.warning("File not found: {}", p)
            return []
        suffix = p.suffix.lower()
        text = self._read_file(p, suffix)
        if not text:
            return []
        source_meta = {"file": str(p), "suffix": suffix, "filename": p.name}
        if metadata:
            source_meta.update(metadata)
        return self.chunk_text(text, source=str(p), metadata=source_meta)

    def _read_file(self, path: Path, suffix: str) -> str:
        try:
            if suffix == ".pdf":
                return self._read_pdf(path)
            elif suffix in (".md", ".mdx"):
                return path.read_text(encoding="utf-8", errors="replace")
            elif suffix in (
                ".txt",
                ".py",
                ".js",
                ".ts",
                ".rs",
                ".go",
                ".java",
                ".c",
                ".cpp",
                ".h",
                ".hpp",
                ".rb",
                ".php",
                ".swift",
                ".kt",
                ".scala",
                ".r",
                ".sql",
                ".sh",
                ".yaml",
                ".yml",
                ".toml",
                ".ini",
                ".cfg",
                ".conf",
                ".json",
                ".xml",
                ".html",
                ".css",
                ".scss",
            ):
                return path.read_text(encoding="utf-8", errors="replace")
            else:
                try:
                    return path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    return ""
        except Exception as e:
            logger.warning("Failed to read {}: {}", path, e)
            return ""

    def _read_pdf(self, path: Path) -> str:
        try:
            import pypdf

            reader = pypdf.PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            logger.warning("pypdf not installed, skipping PDF: {}", path)
            return ""
        except Exception as e:
            logger.warning("Failed to parse PDF {}: {}", path, e)
            return ""

    def chunk_directory(
        self, dir_path: str | Path, glob_pattern: str = "**/*", metadata: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        p = Path(dir_path)
        if not p.is_dir():
            logger.warning("Directory not found: {}", p)
            return []
        all_chunks = []
        for fpath in sorted(p.glob(glob_pattern)):
            if fpath.is_file() and not fpath.name.startswith("."):
                chunks = self.chunk_file(fpath, metadata=metadata)
                all_chunks.extend(chunks)
        return all_chunks

    @staticmethod
    def format_for_prompt(chunks: list[dict[str, Any]], max_chunks: int = 5) -> str:
        selected = chunks[:max_chunks]
        parts = []
        for i, c in enumerate(selected):
            source = c.get("source", c.get("file", "unknown"))
            parts.append(f"[{i + 1}] from {source}:\n{c['text'][:1000]}")
        return "\n\n---\n\n".join(parts)

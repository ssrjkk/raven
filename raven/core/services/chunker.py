from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Chunk:
    text: str
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkerResult:
    chunks: list[Chunk]
    strategy: str
    total_tokens: int


class Chunker:
    STRATEGIES = ("semantic", "fixed", "sliding")

    def __init__(self, max_chars: int = 800, overlap: int = 100) -> None:
        self.max_chars = max(max_chars, 100)
        self.overlap = min(overlap, self.max_chars)

    def chunk(self, text: str, strategy: str = "semantic", metadata: dict[str, Any] | None = None) -> ChunkerResult:
        strategy = strategy if strategy in self.STRATEGIES else "semantic"
        if strategy == "fixed":
            chunks = self._fixed_chunk(text)
        elif strategy == "sliding":
            chunks = self._sliding_chunk(text)
        else:
            chunks = self._semantic_chunk(text)
        total = sum(len(c.text) for c in chunks)
        return ChunkerResult(chunks=chunks, strategy=strategy, total_tokens=total)

    def _semantic_chunk(self, text: str) -> list[Chunk]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[Chunk] = []
        buffer: list[str] = []
        buf_len = 0
        for para in paragraphs:
            para_len = len(para)
            if buf_len + para_len > self.max_chars and buffer:
                chunks.append(Chunk(text="\n\n".join(buffer), index=len(chunks)))
                overlap_text = buffer[-1] if self.overlap and buffer else ""
                buffer = [overlap_text] if overlap_text else []
                buf_len = len(overlap_text)
            buffer.append(para)
            buf_len += para_len
        if buffer:
            chunks.append(Chunk(text="\n\n".join(buffer), index=len(chunks)))
        return chunks

    def _fixed_chunk(self, text: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        start = 0
        while start < len(text):
            end = start + self.max_chars
            chunks.append(Chunk(text=text[start:end], index=len(chunks)))
            start = end
        return chunks

    def _sliding_chunk(self, text: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        start = 0
        stride = self.max_chars - self.overlap
        if stride < 1:
            stride = 1
        while start < len(text):
            end = start + self.max_chars
            chunks.append(Chunk(text=text[start:end], index=len(chunks)))
            start += stride
        return chunks

from __future__ import annotations

import contextlib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from raven.core.memory.manager import MemoryManager


async def detect_patterns(memory: MemoryManager, min_frequency: int = 2) -> list[dict[str, str | int]]:
    raw_lines = await _read_all_lt_lines(memory)
    if not raw_lines:
        return []

    topics = Counter[str]()
    for line in raw_lines:
        content = line.lstrip("# ")
        if ":" in content:
            content = content.split(":", 1)[-1].strip()
        segments = content.lower().split()
        for i in range(len(segments) - 1):
            phrase = f"{segments[i]} {segments[i+1]}"
            if len(phrase) > 8:
                topics[phrase] += 1

    patterns: list[dict[str, str | int]] = []
    for phrase, count in topics.most_common(10):
        if count >= min_frequency:
            patterns.append({
                "type": "recurring_phrase",
                "pattern": phrase,
                "frequency": count,
            })

    reported_topics = await _extract_recurring_topics(memory, raw_lines)
    for topic, count in reported_topics:
        patterns.append({
            "type": "recurring_topic",
            "pattern": topic,
            "frequency": count,
        })

    patterns.sort(key=lambda p: int(p["frequency"]), reverse=True)
    top = [p for p in patterns if int(p["frequency"]) >= min_frequency][:5]
    if top:
        logger.info("[dream] detected {} patterns", len(top))
    return top


async def _read_all_lt_lines(memory: MemoryManager) -> list[str]:
    root = memory.long_term.root if hasattr(memory.long_term, "root") else Path(".raven/memory")
    if not root.is_dir():
        return []
    lines: list[str] = []
    for f in sorted(root.iterdir()):
        if f.suffix == ".md":
                with contextlib.suppress(Exception):
                    text = f.read_text(encoding="utf-8", errors="replace")
                    lines.extend(text.splitlines())
    return [ln for ln in lines if ln.strip()]


async def _extract_recurring_topics(memory: MemoryManager, raw_lines: list[str]) -> list[tuple[str, int]]:
    prefixes = Counter[str]()
    for line in raw_lines:
        content = line.lstrip("# ")
        parts = content.split(":", 1)
        if len(parts) >= 2 and parts[0].strip():
            prefixes[parts[0].strip()] += 1
    return [(k, v) for k, v in prefixes.most_common(5) if v >= 2]

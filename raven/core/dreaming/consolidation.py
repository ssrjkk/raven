from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from raven.core.memory.manager import MemoryManager


async def consolidate_memories(memory: MemoryManager) -> dict[str, int]:
    stats: dict[str, int] = {
        "working_expired": 0,
        "promoted_to_session": 0,
        "promoted_to_long_term": 0,
        "entities_added": 0,
    }

    expired = await memory.working.cleanup_expired()
    stats["working_expired"] = expired

    working_keys = await memory.working.list_keys()
    for key in working_keys[:10]:
        value = await memory.working.recall(key)
        if value is None:
            continue
        await memory.session.store(key, value, {"session_id": "_consolidated_", "role": "system"})
        await memory.working.delete(key)
        stats["promoted_to_session"] += 1

    session_keys = await memory.session.list_keys()
    for key in session_keys[:5]:
        value = await memory.session.recall(key)
        if value is None:
            continue
        await memory.long_term.store(f"dream:{key}", value[:1000])
        stats["promoted_to_long_term"] += 1

    lt_keys = await memory.long_term.list_keys()
    for key in lt_keys[-3:]:
        value = await memory.long_term.recall(key)
        if value and ":" in value:
            category = value.split(":")[0].strip()
            await memory.knowledge.store(f"dream:{key}", value, {"type": "dream_entity", "category": category})
            stats["entities_added"] += 1

    logger.info(
        "[dream] consolidation: {} expired, {}→session, {}→long-term, {} entities",
        stats["working_expired"],
        stats["promoted_to_session"],
        stats["promoted_to_long_term"],
        stats["entities_added"],
    )
    return stats


async def extract_topics_from_lt(memory: MemoryManager, limit: int = 20) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for cat in ("user", "project", "lessons", "general"):
        entries = await memory.long_term.search(cat, limit=5)
        if entries and cat not in seen:
            seen.add(cat)
            topics.append(cat)
        if len(topics) >= limit:
            break
    return topics

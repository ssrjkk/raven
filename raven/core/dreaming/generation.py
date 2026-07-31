from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from raven.core.memory.manager import MemoryManager


async def generate_skills(
    memory: MemoryManager,
    patterns: list[dict[str, str | int]],
) -> list[dict[str, str]]:
    if not patterns:
        return []

    skills: list[dict[str, str]] = []
    for pattern in patterns:
        ptype = str(pattern.get("type", ""))
        ptext = str(pattern.get("pattern", ""))
        if isinstance(ptext, str) and len(ptext) > 2:
            skill = _pattern_to_skill(ptype, ptext)
            if skill:
                skills.append(skill)

    logger.info("[dream] generated {} skill proposals from {} patterns", len(skills), len(patterns))
    return skills


def _pattern_to_skill(ptype: str, ptext: str) -> dict[str, str] | None:
    if ptype == "recurring_topic":
        topic = ptext.replace("_", " ").replace(":", "").strip().title()
        return {
            "name": f"dream-{ptext.replace('_', '-').replace(':', '').lower()[:30]}",
            "description": f"Handle common topic: {topic}",
            "instructions": f"Address tasks related to {topic}. Follow established patterns from previous work.",
        }
    if ptype == "recurring_phrase":
        phrase = ptext.strip().capitalize()
        key = phrase.replace(" ", "-").lower()[:30]
        return {
            "name": f"dream-{key}",
            "description": f"Pattern-based skill for: {phrase}",
            "instructions": f"When encountering '{phrase}', follow these steps:\n1. Acknowledge the pattern\n2. Apply known solutions\n3. Verify the result matches expectations",
        }
    return None


async def apply_skill_proposals(
    proposals: list[dict[str, str]],
    register_fn: Any = None,
) -> list[str]:
    applied: list[str] = []
    for proposal in proposals:
        name = proposal.get("name", "")
        if not name:
            continue
        if register_fn:
            try:
                register_fn(name, proposal.get("description", ""), proposal.get("instructions", ""))
                applied.append(name)
            except Exception as e:
                logger.warning("[dream] failed to register skill '{}': {}", name, e)
    if applied:
        logger.info("[dream] applied {} skill proposals", len(applied))
    return applied

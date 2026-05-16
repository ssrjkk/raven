from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger


class Skill:
    def __init__(self, name: str, description: str, prompt: str, tools: list[str] | None = None, handler: Any = None):
        self.name = name
        self.description = description
        self.prompt = prompt
        self.tools = tools or []
        self._handler = handler

    async def execute(self, *args, **kwargs) -> str | None:
        if self._handler:
            if asyncio.iscoroutinefunction(self._handler):
                return await self._handler(*args, **kwargs)
            return self._handler(*args, **kwargs)
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt[:200],
            "tools": self.tools,
        }


class SkillsRegistry:
    def __init__(self, skills_dir: str | Path | None = None):
        self._skills: dict[str, Skill] = {}
        self._skills_dir = Path(skills_dir) if skills_dir else None

    def register(self, skill: Skill):
        self._skills[skill.name] = skill
        logger.info("Registered skill: {}", skill.name)

    def register_from_dir(self, path: Path):
        if not path.exists():
            return
        for skill_dir in path.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    content = skill_file.read_text(encoding="utf-8")
                    lines = content.strip().split("\n")
                    description = lines[0] if lines else skill_dir.name
                    self._skills[skill_dir.name] = Skill(
                        name=skill_dir.name,
                        description=description,
                        prompt=content,
                    )
                    logger.debug("Loaded skill: {}", skill_dir.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def get_prompt(self, name: str) -> str:
        skill = self.get(name)
        return skill.prompt if skill else ""

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def list_names(self) -> list[str]:
        return list(self._skills.keys())

    def active_prompts(self, names: list[str]) -> str:
        parts = []
        for name in names:
            skill = self.get(name)
            if skill:
                parts.append(f"## Skill: {skill.name}\n{skill.prompt}")
        return "\n\n".join(parts)

    def clear(self):
        self._skills.clear()


skills_registry = SkillsRegistry()

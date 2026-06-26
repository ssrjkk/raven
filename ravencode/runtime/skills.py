from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class Skill:
    name: str
    description: str = ""
    instructions: str = ""
    license: str = ""
    compatibility: list[str] = field(default_factory=list)
    permissions: dict[str, str] = field(default_factory=dict)
    source: str = ""

    @classmethod
    def from_file(cls, path: Path) -> Skill | None:
        text = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        instructions = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1])
                except Exception as e:
                    logger.warning("Failed to parse skill frontmatter {}: {}", path, e)
                    meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                instructions = parts[2].strip()
        name = meta.get("name", path.stem)
        return cls(
            name=name,
            description=meta.get("description", ""),
            instructions=instructions,
            license=meta.get("license", ""),
            compatibility=meta.get("compatibility", []),
            permissions=meta.get("permissions", {}),
            source=str(path),
        )


_SKILL_DIRS = [
    Path(".opencode") / "skills",
    Path.home() / ".config" / "ravencode" / "skills",
    Path(".claude") / "skills",
    Path(".agents") / "skills",
]


def discover_skills(extra_dirs: list[Path] | None = None) -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    dirs = list(_SKILL_DIRS)
    if extra_dirs:
        dirs.extend(extra_dirs)
    for skill_dir in dirs:
        if not skill_dir.is_dir():
            continue
        for entry in sorted(skill_dir.iterdir()):
            if entry.is_dir():
                skill_file = entry / "SKILL.md"
                if not skill_file.exists():
                    continue
            elif entry.name.endswith(".md"):
                skill_file = entry
            else:
                continue
            skill = Skill.from_file(skill_file)
            if skill:
                skills[skill.name] = skill
    return skills


def get_skill(name: str) -> Skill | None:
    return discover_skills().get(name)

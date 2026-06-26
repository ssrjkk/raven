from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


@dataclass
class CustomCommand:
    name: str
    prompt: str
    description: str = ""
    agent: str = ""
    model: str = ""
    subtask: bool = False
    source: str = ""

    @classmethod
    def from_markdown(cls, path: Path) -> CustomCommand | None:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            logger.warning("Missing frontmatter in {}", path)
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            logger.warning("Invalid frontmatter in {}", path)
            return None
        try:
            meta = yaml.safe_load(parts[1])
        except Exception as e:
            logger.warning("Failed to parse frontmatter in {}: {}", path, e)
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        prompt_text = parts[2].strip()
        return cls(
            name=path.stem,
            prompt=meta.get("prompt", prompt_text),
            description=meta.get("description", meta.get("description", "")),
            agent=meta.get("agent", ""),
            model=meta.get("model", ""),
            subtask=meta.get("subtask", False),
            source=str(path),
        )

    def render_prompt(self, args: str = "", file_refs: dict[str, str] | None = None) -> str:
        result = self.prompt
        result = result.replace("$ARGUMENTS", args)
        result = result.replace("$1", args.split()[0] if args.strip() else "")
        result = result.replace("$2", args.split()[1] if len(args.split()) > 1 else "")
        result = result.replace("$3", args.split()[2] if len(args.split()) > 2 else "")
        if file_refs:
            for ref, content in file_refs.items():
                result = result.replace(f"@{ref}", f"\n```\n{content}\n```\n")
        return result


_COMMAND_DIRS = [
    Path(".opencode") / "commands",
    Path.home() / ".config" / "ravencode" / "commands",
]


def discover_commands(extra_dirs: list[Path] | None = None) -> dict[str, CustomCommand]:
    commands: dict[str, CustomCommand] = {}
    dirs = list(_COMMAND_DIRS)
    if extra_dirs:
        dirs.extend(extra_dirs)
    for cmd_dir in dirs:
        if not cmd_dir.is_dir():
            continue
        for f in sorted(cmd_dir.glob("*.md")):
            cmd = CustomCommand.from_markdown(f)
            if cmd:
                commands[cmd.name] = cmd
    return commands


def commands_from_config(config_commands: list[dict[str, Any]]) -> dict[str, CustomCommand]:
    commands: dict[str, CustomCommand] = {}
    for entry in config_commands:
        name = entry.get("name", "")
        if not name:
            continue
        prompt = entry.get("prompt", entry.get("template", ""))
        commands[name] = CustomCommand(
            name=name,
            prompt=prompt,
            description=entry.get("description", ""),
            agent=entry.get("agent", ""),
            model=entry.get("model", ""),
            subtask=entry.get("subtask", False),
            source="config",
        )
    return commands

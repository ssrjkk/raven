from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


class CustomAgentDef:
    def __init__(self, name: str, data: dict[str, Any]) -> None:
        self.name = name
        self.system_prompt: str = data.get("system_prompt", "")
        self.max_steps: int = data.get("max_steps", 30)
        self.confirm_dangerous: bool = data.get("confirm_dangerous", True)
        self.diff_preview: bool = data.get("diff_preview", True)
        self.proactive_scan: bool = data.get("proactive_scan", True)
        self.tools: list[str] | None = data.get("tools")
        self.restricted_tools: list[str] = data.get("restricted_tools", [])
        self.description: str = data.get("description", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "system_prompt": self.system_prompt,
            "max_steps": self.max_steps,
            "confirm_dangerous": self.confirm_dangerous,
            "diff_preview": self.diff_preview,
            "proactive_scan": self.proactive_scan,
            "tools": self.tools,
            "restricted_tools": self.restricted_tools,
            "description": self.description,
        }


def load_agents_config(path: str | None = None) -> dict[str, CustomAgentDef]:
    candidates = [
        Path(path).expanduser().resolve() if path else None,
        Path.cwd() / "ravencode" / "agents" / "custom_agents.json",
        Path.cwd() / "custom_agents.json",
        Path.home() / ".config" / "raven" / "custom_agents.json",
    ]
    for c in candidates:
        if c and c.is_file():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                agents: dict[str, CustomAgentDef] = {}
                for name, cfg in data.get("agents", {}).items():
                    agents[name] = CustomAgentDef(name, cfg)
                logger.info("Loaded {} custom agents from {}", len(agents), c)
                return agents
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load agents config {}: {}", c, exc)
    return {}


_custom_agents: dict[str, CustomAgentDef] | None = None


def get_custom_agents(path: str | None = None) -> dict[str, CustomAgentDef]:
    global _custom_agents
    if _custom_agents is None:
        _custom_agents = load_agents_config(path)
    return _custom_agents


def reload_custom_agents(path: str | None = None) -> dict[str, CustomAgentDef]:
    global _custom_agents
    _custom_agents = load_agents_config(path)
    return _custom_agents

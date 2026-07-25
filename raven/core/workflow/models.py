from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TemplateCategory(StrEnum):
    DAILY = "daily"
    DEV = "dev"
    MONITORING = "monitoring"
    PRODUCTIVITY = "productivity"
    COMMUNICATION = "communication"
    DATA = "data"


class TemplateTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    INTERVAL = "interval"
    EVENT = "event"


@dataclass
class TemplateStep:
    description: str
    tool: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowTemplate:
    id: str
    name: str
    description: str
    category: TemplateCategory
    trigger: TemplateTrigger = TemplateTrigger.MANUAL
    default_schedule: str | None = None
    default_interval: int | None = None
    config_schema: dict[str, Any] = field(default_factory=dict)
    system_prompt: str | None = None
    steps_goal: str | None = None
    predefined_steps: list[TemplateStep] = field(default_factory=list)
    icon: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "trigger": self.trigger.value,
            "default_schedule": self.default_schedule,
            "default_interval": self.default_interval,
            "config_schema": self.config_schema,
            "system_prompt": self.system_prompt,
            "steps_goal": self.steps_goal,
            "predefined_steps": [
                {"description": s.description, "tool": s.tool, "params": s.params} for s in self.predefined_steps
            ],
            "icon": self.icon,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowTemplate:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            category=TemplateCategory(data.get("category", "daily")),
            trigger=TemplateTrigger(data.get("trigger", "manual")),
            default_schedule=data.get("default_schedule"),
            default_interval=data.get("default_interval"),
            config_schema=data.get("config_schema", {}),
            system_prompt=data.get("system_prompt"),
            steps_goal=data.get("steps_goal"),
            predefined_steps=[TemplateStep(**s) for s in data.get("predefined_steps", [])],
            icon=data.get("icon", ""),
        )

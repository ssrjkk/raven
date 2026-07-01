from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouteRule:
    pattern: str
    agent_id: str
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(self, channel: str, account: str | None = None) -> bool:
        if self.pattern == f"channel:{channel}":
            return True
        if account and self.pattern == f"account:{account}":
            return True
        return self.pattern == "*"


class RoutingEngine:
    def __init__(self) -> None:
        self.rules: list[RouteRule] = []

    def add_rule(self, pattern: str, agent_id: str, priority: int = 0, **metadata: Any) -> None:
        self.rules.append(RouteRule(pattern=pattern, agent_id=agent_id, priority=priority, metadata=metadata))
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, pattern: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.pattern != pattern]
        return len(self.rules) < before

    def route(self, channel: str, account: str | None = None) -> str:
        for rule in self.rules:
            if rule.matches(channel, account):
                return rule.agent_id
        return "default"

    def load_config(self, config: dict[str, str]) -> None:
        for pattern, agent_id in config.items():
            self.add_rule(pattern, agent_id)

    def list_rules(self) -> list[dict[str, Any]]:
        return [
            {"pattern": r.pattern, "agent_id": r.agent_id, "priority": r.priority, "metadata": r.metadata}
            for r in self.rules
        ]

    @classmethod
    def from_config(cls, config: dict[str, str]) -> RoutingEngine:
        engine = cls()
        engine.load_config(config)
        return engine


DEFAULT_ROUTING: dict[str, str] = {
    "channel:telegram": "agent:personal",
    "channel:slack": "agent:work",
    "channel:discord": "agent:community",
    "channel:whatsapp": "agent:personal",
    "channel:signal": "agent:personal",
    "channel:webchat": "agent:default",
    "channel:cli": "agent:build",
    "*": "agent:default",
}

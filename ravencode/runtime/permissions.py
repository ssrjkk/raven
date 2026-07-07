from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PermissionAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class PermissionRule:
    tool: str
    action: PermissionAction
    reason: str = ""


class PermissionManager:
    def __init__(self, rules: list[PermissionRule] | None = None) -> None:
        self._rules: list[PermissionRule] = rules or []
        self._default_action: PermissionAction = PermissionAction.ALLOW

    @property
    def rules(self) -> list[PermissionRule]:
        return list(self._rules)

    def add_rule(self, rule: PermissionRule) -> None:
        self._rules.append(rule)

    def allow(self, tool: str, reason: str = "") -> None:
        self._rules.append(PermissionRule(tool=tool, action=PermissionAction.ALLOW, reason=reason))

    def deny(self, tool: str, reason: str = "") -> None:
        self._rules.append(PermissionRule(tool=tool, action=PermissionAction.DENY, reason=reason))

    def is_allowed(self, tool: str, args: dict[str, Any] | None = None) -> tuple[bool, str]:
        for rule in reversed(self._rules):
            if rule.tool == tool or rule.tool == "*":
                if rule.action == PermissionAction.DENY:
                    return False, rule.reason or f"tool '{tool}' denied by permission rule"
                return True, ""
        return self._default_action == PermissionAction.ALLOW, ""

    def to_dict(self) -> list[dict[str, str]]:
        return [
            {"tool": r.tool, "action": r.action.value, "reason": r.reason}
            for r in self._rules
        ]

    @classmethod
    def from_dict(cls, items: list[dict[str, str]]) -> PermissionManager:
        rules = []
        for item in items:
            raw = item.get("action", "deny")
            try:
                action = PermissionAction(raw)
            except ValueError:
                action = PermissionAction.DENY
            rules.append(PermissionRule(
                tool=item.get("tool", "*"),
                action=action,
                reason=item.get("reason", ""),
            ))
        return cls(rules=rules)


def default_deny_rules() -> list[PermissionRule]:
    return [
        PermissionRule(tool="bash", action=PermissionAction.DENY, reason="not allowed in read-only mode"),
        PermissionRule(tool="write", action=PermissionAction.DENY, reason="not allowed in read-only mode"),
        PermissionRule(tool="edit", action=PermissionAction.DENY, reason="not allowed in read-only mode"),
        PermissionRule(tool="git_commit", action=PermissionAction.DENY, reason="not allowed in read-only mode"),
        PermissionRule(tool="git_add", action=PermissionAction.DENY, reason="not allowed in read-only mode"),
        PermissionRule(tool="task", action=PermissionAction.DENY, reason="not allowed in read-only mode"),
    ]

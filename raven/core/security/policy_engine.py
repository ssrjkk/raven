from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Op(StrEnum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    REGEX = "regex"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"
    EXISTS = "exists"
    AND = "and"
    OR = "or"
    NOT = "not"
    TRUE = "true"


def _resolve(input_data: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = input_data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


@dataclass
class ConditionNode:
    op: Op
    path: str = ""
    value: Any = None
    children: list[ConditionNode] = field(default_factory=list)

    def evaluate(self, input_data: dict[str, Any]) -> bool:
        try:
            return self._evaluate(input_data)
        except Exception:
            return False

    def _evaluate(self, input_data: dict[str, Any]) -> bool:
        if self.op == Op.TRUE:
            return True

        if self.op == Op.AND:
            return all(c.evaluate(input_data) for c in self.children)

        if self.op == Op.OR:
            return any(c.evaluate(input_data) for c in self.children)

        if self.op == Op.NOT:
            return not self.children[0].evaluate(input_data) if self.children else False

        actual = _resolve(input_data, self.path)

        if self.op == Op.EQ:
            return actual == self.value  # type: ignore[no-any-return]
        if self.op == Op.NEQ:
            return actual != self.value  # type: ignore[no-any-return]
        if self.op == Op.GT:
            return actual is not None and actual > self.value
        if self.op == Op.GTE:
            return actual is not None and actual >= self.value
        if self.op == Op.LT:
            return actual is not None and actual < self.value
        if self.op == Op.LTE:
            return actual is not None and actual <= self.value
        if self.op == Op.IN:
            return actual in (self.value or [])
        if self.op == Op.NOT_IN:
            return actual not in (self.value or [])
        if self.op == Op.CONTAINS:
            return self.value in str(actual) if actual is not None else False
        if self.op == Op.REGEX:
            return bool(re.match(self.value, str(actual))) if actual is not None else False
        if self.op == Op.STARTSWITH:
            return str(actual).startswith(self.value) if actual is not None else False
        if self.op == Op.ENDSWITH:
            return str(actual).endswith(self.value) if actual is not None else False
        if self.op == Op.EXISTS:
            return (actual is not None) if self.value else (actual is None)

        return False

    @classmethod
    def from_dict(cls, spec: Any) -> ConditionNode:
        if not isinstance(spec, dict):
            return cls(Op.TRUE if spec else Op.NOT, children=[cls(Op.TRUE)] if not spec else [])

        if len(spec) == 0:
            return cls(Op.TRUE)

        children: list[ConditionNode] = []

        if "and" in spec:
            and_children = [cls.from_dict(c) for c in spec["and"]]
            children.append(cls(Op.AND, children=and_children))

        if "or" in spec:
            or_children = [cls.from_dict(c) for c in spec["or"]]
            children.append(cls(Op.OR, children=or_children))

        if "not" in spec:
            children.append(cls(Op.NOT, children=[cls.from_dict(spec["not"])]))

        if "any" in spec and isinstance(spec["any"], dict):
            any_children = [cls(Op.EQ, path=k, value=v) for k, v in spec["any"].items()]
            children.append(cls(Op.OR, children=any_children))

        if "match" in spec:
            m = spec["match"]
            children.append(cls(Op.REGEX, path=m.get("field", ""), value=m.get("pattern", "")))

        for key, condition in spec.items():
            if key in ("and", "or", "not", "any", "match"):
                continue
            if isinstance(condition, dict) and any(k.startswith("$") for k in condition):
                sub = []
                for op_key, op_val in condition.items():
                    mapped = _MAP_OP.get(op_key)
                    if mapped:
                        sub.append(cls(mapped, path=key, value=op_val))
                    else:
                        sub.append(cls(Op.EQ, path=key, value=op_val))
                if len(sub) == 1:
                    children.append(sub[0])
                else:
                    children.append(cls(Op.AND, children=sub))
            else:
                children.append(cls(Op.EQ, path=key, value=condition))

        if len(children) == 1:
            return children[0]
        return cls(Op.AND, children=children)

    def __repr__(self) -> str:
        if self.op == Op.TRUE:
            return "TRUE"
        if self.op in (Op.AND, Op.OR):
            return f"{self.op.value.upper()}({', '.join(repr(c) for c in self.children)})"
        if self.op == Op.NOT:
            return f"NOT({self.children[0]!r})"
        return f"{self.path} {self.op.value}({self.value!r})"


_MAP_OP: dict[str, Op] = {
    "$gt": Op.GT,
    "$gte": Op.GTE,
    "$lt": Op.LT,
    "$lte": Op.LTE,
    "$in": Op.IN,
    "$not_in": Op.NOT_IN,
    "$contains": Op.CONTAINS,
    "$regex": Op.REGEX,
    "$startswith": Op.STARTSWITH,
    "$endswith": Op.ENDSWITH,
    "$exists": Op.EXISTS,
    "$neq": Op.NEQ,
}


class Rule:
    def __init__(
        self,
        name: str,
        condition: dict[str, Any] | ConditionNode,
        effect: str,
        priority: int = 0,
        description: str = "",
        tags: list[str] | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ):
        self.name = name
        self._condition = condition if isinstance(condition, ConditionNode) else ConditionNode.from_dict(condition)
        self.effect = effect
        self.priority = priority
        self.description = description
        self.tags = tags or []
        self.enabled = enabled
        self.metadata = metadata or {}

    def evaluate(self, input_data: dict[str, Any]) -> bool:
        return self._condition.evaluate(input_data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "effect": self.effect,
            "priority": self.priority,
            "description": self.description,
            "tags": self.tags,
            "enabled": self.enabled,
        }


class RuleSet:
    def __init__(self, rules: list[Rule] | None = None, name: str = ""):
        self.name = name
        self.rules = sorted(rules or [], key=lambda r: r.priority, reverse=True)

    def evaluate(self, input_data: dict[str, Any]) -> tuple[str | None, str | None]:
        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.evaluate(input_data):
                return rule.effect, rule.name
        return None, None

    def add_rule(self, rule: Rule):
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def to_dict(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.rules]


class PolicyEngine:
    def __init__(self, rules_dir: str = "policy"):
        self._rules_dir = Path(rules_dir)
        self._rulesets: dict[str, RuleSet] = {}

    def load_ruleset(self, name: str, path: str | None = None) -> RuleSet:
        filepath = Path(path or self._rules_dir / f"{name}.yaml")
        if not filepath.exists():
            filepath = Path(path or self._rules_dir / f"{name}.json")
        if not filepath.exists():
            return RuleSet(name=name)

        raw = filepath.read_text(encoding="utf-8")
        if filepath.suffix in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(raw)
        else:
            data = json.loads(raw)

        rules = []
        for item in data if isinstance(data, list) else data.get("rules", []):
            rules.append(
                Rule(
                    name=item.get("name", "unnamed"),
                    condition=item.get("condition", {}),
                    effect=item.get("effect", "deny"),
                    priority=item.get("priority", 0),
                    description=item.get("description", ""),
                    tags=item.get("tags", []),
                    enabled=item.get("enabled", True),
                    metadata=item.get("metadata", {}),
                )
            )

        rs = RuleSet(rules, name=name)
        self._rulesets[name] = rs
        return rs

    def get_ruleset(self, name: str) -> RuleSet | None:
        return self._rulesets.get(name)

    def evaluate(self, ruleset_name: str, input_data: dict[str, Any]) -> tuple[str | None, str | None]:
        rs = self.get_ruleset(ruleset_name)
        if rs is None:
            rs = self.load_ruleset(ruleset_name)
        return rs.evaluate(input_data)

    def check(self, ruleset: str, input_data: dict[str, Any]) -> bool:
        effect, _ = self.evaluate(ruleset, input_data)
        return effect != "deny"

    def to_dict(self) -> dict[str, Any]:
        return {name: rs.to_dict() for name, rs in self._rulesets.items()}


policy_engine = PolicyEngine()

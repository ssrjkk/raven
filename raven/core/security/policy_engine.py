from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Op(str, Enum):
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


@dataclass
class TraceStep:
    condition: ConditionNode
    result: bool
    detail: str = ""
    children: list[TraceStep] = field(default_factory=list)


@dataclass
class EvaluationTrace:
    rule_name: str
    effect: str
    matched: bool
    steps: list[TraceStep] = field(default_factory=list)


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

    def evaluate_traced(self, input_data: dict[str, Any]) -> tuple[bool, EvaluationTrace]:
        trace = EvaluationTrace(rule_name=self.name, effect=self.effect, matched=False)
        result = self._eval_with_trace(self._condition, input_data, trace.steps)
        trace.matched = result
        return result, trace

    def _eval_with_trace(self, node: ConditionNode, input_data: dict[str, Any], steps: list[TraceStep]) -> bool:
        step = TraceStep(condition=node, result=False)
        result = node.evaluate(input_data)
        step.result = result
        step.detail = _fmt_trace(node, result)
        if node.children:
            for child in node.children:
                child_step = TraceStep(condition=child, result=False)
                child_result = child.evaluate(input_data)
                child_step.result = child_result
                child_step.detail = _fmt_trace(child, child_result)
                step.children.append(child_step)
        steps.append(step)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "effect": self.effect,
            "priority": self.priority,
            "description": self.description,
            "tags": self.tags,
            "enabled": self.enabled,
        }


def _fmt_trace(node: ConditionNode, result: bool) -> str:
    if node.op == Op.TRUE:
        return f"TRUE -> {result}"
    if node.op in (Op.AND, Op.OR):
        return f"{node.op.value.upper()} -> {result}"
    if node.op == Op.NOT:
        return f"NOT -> {result}"
    return f"{node.path} {node.op.value}({node.value!r}) -> {result}"


@dataclass
class RuleDecision:
    effect: str | None
    rule_name: str | None
    trace: list[EvaluationTrace] | None = None


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

    def evaluate_detailed(self, input_data: dict[str, Any]) -> RuleDecision:
        traces: list[EvaluationTrace] = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            matched, trace = rule.evaluate_traced(input_data)
            traces.append(trace)
            if matched:
                return RuleDecision(effect=rule.effect, rule_name=rule.name, trace=traces)
        return RuleDecision(effect=None, rule_name=None, trace=traces)

    def add_rule(self, rule: Rule):
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def to_dict(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.rules]


class PolicyEngine:
    def __init__(self, rules_dir: str = "policy"):
        self._rules_dir = Path(rules_dir)
        self._rulesets: dict[str, RuleSet] = {}
        self._lock = threading.RLock()
        self._last_mtime: dict[str, float] = {}
        self._checksums: dict[str, str] = {}
        self._watcher_active = False
        self._watcher_thread: threading.Thread | None = None

    def load_ruleset(self, name: str, path: str | None = None) -> RuleSet:
        filepath = Path(path or self._rules_dir / f"{name}.yaml")
        if not filepath.exists():
            filepath = Path(path or self._rules_dir / f"{name}.json")
        if not filepath.exists():
            rs = RuleSet(name=name)
            with self._lock:
                self._rulesets[name] = rs
            return rs

        raw = filepath.read_text(encoding="utf-8")
        if filepath.suffix in (".yaml", ".yml"):
            try:
                import yaml

                data = yaml.safe_load(raw)
            except ImportError:
                rules = self._parse_simple(raw)
                rs = RuleSet(rules, name=name)
                with self._lock:
                    self._rulesets[name] = rs
                return rs
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
        with self._lock:
            self._rulesets[name] = rs
            self._checksums[name] = hashlib.sha256(raw.encode()).hexdigest()
            try:
                self._last_mtime[name] = filepath.stat().st_mtime
            except OSError:
                pass
        return rs

    def get_ruleset(self, name: str) -> RuleSet | None:
        with self._lock:
            return self._rulesets.get(name)

    def evaluate(self, ruleset_name: str, input_data: dict[str, Any]) -> tuple[str | None, str | None]:
        rs = self.get_ruleset(ruleset_name)
        if rs is None:
            rs = self.load_ruleset(ruleset_name)
        return rs.evaluate(input_data)

    def evaluate_detailed(self, ruleset_name: str, input_data: dict[str, Any]) -> RuleDecision:
        rs = self.get_ruleset(ruleset_name)
        if rs is None:
            rs = self.load_ruleset(ruleset_name)
        return rs.evaluate_detailed(input_data)

    def check(self, ruleset: str, input_data: dict[str, Any]) -> bool:
        effect, _ = self.evaluate(ruleset, input_data)
        return effect != "deny"

    def start_watcher(self, interval: float = 5.0):
        if self._watcher_active:
            return
        self._watcher_active = True

        def _watch():
            while self._watcher_active:
                self._reload_changed()
                time.sleep(interval)

        self._watcher_thread = threading.Thread(target=_watch, daemon=True)
        self._watcher_thread.start()

    def stop_watcher(self):
        self._watcher_active = False
        if self._watcher_thread:
            self._watcher_thread.join(timeout=2.0)

    def _reload_changed(self):
        for name, last_mtime in list(self._last_mtime.items()):
            filepath = self._rules_dir / f"{name}.yaml"
            if not filepath.exists():
                filepath = self._rules_dir / f"{name}.json"
            if not filepath.exists():
                continue
            try:
                current_mtime = filepath.stat().st_mtime
                if current_mtime > last_mtime:
                    self.load_ruleset(name)
            except OSError:
                pass

    def _parse_simple(self, text: str) -> list[Rule]:
        rules: list[Rule] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            if ":" in line:
                parts = line.split(":", 1)
                name = parts[0].strip()
                rest = parts[1].strip()
                if " " in rest:
                    effect, cond_str = rest.split(" ", 1)
                else:
                    effect = rest
                    cond_str = ""
                condition = {}
                if cond_str:
                    condition = {"match": {"field": "tool", "pattern": cond_str}}
                rules.append(Rule(name=name or f"rule_{len(rules)}", condition=condition, effect=effect))
        return rules

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {name: rs.to_dict() for name, rs in self._rulesets.items()}


policy_engine = PolicyEngine()

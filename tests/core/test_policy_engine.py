from __future__ import annotations

import json
import os
import tempfile

from raven.core.security.policy_engine import (
    ConditionNode,
    Op,
    PolicyEngine,
    Rule,
    RuleSet,
)


# ─── ConditionNode from_dict ─────────────────────────────────────────


def test_from_dict_empty():
    node = ConditionNode.from_dict({})
    assert node.op == Op.TRUE
    assert node.evaluate({})


def test_from_dict_implicit_and():
    node = ConditionNode.from_dict({"tool": "exec", "profile": "full"})
    assert node.op == Op.AND
    assert node.evaluate({"tool": "exec", "profile": "full"})
    assert not node.evaluate({"tool": "exec", "profile": "minimal"})


def test_from_dict_or():
    node = ConditionNode.from_dict({"or": [{"tool": "ping"}, {"tool": "exec"}]})
    assert node.op == Op.OR
    assert node.evaluate({"tool": "ping"})
    assert node.evaluate({"tool": "exec"})
    assert not node.evaluate({"tool": "read"})


def test_from_dict_and():
    node = ConditionNode.from_dict({"and": [{"tool": "ping"}, {"profile": "full"}]})
    assert node.op == Op.AND
    assert node.evaluate({"tool": "ping", "profile": "full"})
    assert not node.evaluate({"tool": "ping", "profile": "messaging"})


def test_from_dict_not():
    node = ConditionNode.from_dict({"not": {"tool": "exec"}})
    assert node.op == Op.NOT
    assert node.evaluate({"tool": "ping"})
    assert not node.evaluate({"tool": "exec"})


def test_from_dict_not_with_remaining():
    node = ConditionNode.from_dict({"not": {"tool": "exec"}, "profile": "sandbox"})
    assert node.op == Op.AND
    assert node.evaluate({"tool": "ping", "profile": "sandbox"})
    assert not node.evaluate({"tool": "exec", "profile": "sandbox"})
    assert not node.evaluate({"tool": "ping", "profile": "messaging"})


def test_from_dict_any():
    node = ConditionNode.from_dict({"any": {"tool": "ping", "action": "call"}})
    assert node.op == Op.OR
    assert node.evaluate({"tool": "ping"})
    assert node.evaluate({"action": "call"})
    assert not node.evaluate({"tool": "exec"})


def test_from_dict_match():
    node = ConditionNode.from_dict({"match": {"field": "email", "pattern": r".+@.+\..+"}})
    assert node.op == Op.REGEX
    assert node.evaluate({"email": "user@example.com"})
    assert not node.evaluate({"email": "invalid"})


def test_from_dict_primitive_true():
    node = ConditionNode.from_dict(True)
    assert node.op == Op.TRUE
    assert node.evaluate({})


def test_from_dict_primitive_false():
    node = ConditionNode.from_dict(False)
    assert node.op == Op.NOT
    assert not node.evaluate({})


# ─── ConditionNode evaluate ──────────────────────────────────────────


def test_rule_match_exact():
    rule = Rule("test", {"tool": "ping", "profile": "full"}, "allow", 50)
    assert rule.evaluate({"tool": "ping", "profile": "full"})
    assert not rule.evaluate({"tool": "exec", "profile": "full"})


def test_rule_match_or():
    rule = Rule("test", {"or": [{"tool": "ping"}, {"tool": "exec"}]}, "deny", 100)
    assert rule.evaluate({"tool": "ping"})
    assert rule.evaluate({"tool": "exec"})
    assert not rule.evaluate({"tool": "read"})


def test_rule_match_and():
    rule = Rule("test", {"and": [{"tool": "ping"}, {"profile": "full"}]}, "allow", 50)
    assert rule.evaluate({"tool": "ping", "profile": "full"})
    assert not rule.evaluate({"tool": "ping", "profile": "messaging"})


def test_rule_match_not():
    rule = Rule("test", {"not": {"tool": "exec"}}, "allow", 50)
    assert rule.evaluate({"tool": "ping"})
    assert not rule.evaluate({"tool": "exec"})


def test_rule_match_gt():
    rule = Rule("test", {"count": {"$gt": 5}}, "allow", 50)
    assert rule.evaluate({"count": 10})
    assert not rule.evaluate({"count": 3})


def test_rule_match_gte():
    rule = Rule("test", {"count": {"$gte": 5}}, "allow", 50)
    assert rule.evaluate({"count": 5})
    assert rule.evaluate({"count": 10})
    assert not rule.evaluate({"count": 3})


def test_rule_match_lt():
    rule = Rule("test", {"count": {"$lt": 5}}, "allow", 50)
    assert rule.evaluate({"count": 3})
    assert not rule.evaluate({"count": 10})


def test_rule_match_lte():
    rule = Rule("test", {"count": {"$lte": 5}}, "allow", 50)
    assert rule.evaluate({"count": 5})
    assert rule.evaluate({"count": 3})
    assert not rule.evaluate({"count": 10})


def test_rule_match_in():
    rule = Rule("test", {"role": {"$in": ["admin", "moderator"]}}, "allow", 50)
    assert rule.evaluate({"role": "admin"})
    assert rule.evaluate({"role": "moderator"})
    assert not rule.evaluate({"role": "user"})


def test_rule_match_not_in():
    rule = Rule("test", {"role": {"$not_in": ["admin", "moderator"]}}, "deny", 50)
    assert rule.evaluate({"role": "user"})
    assert not rule.evaluate({"role": "admin"})


def test_rule_match_contains():
    rule = Rule("test", {"path": {"$contains": "/workspace/"}}, "allow", 50)
    assert rule.evaluate({"path": "/home/user/workspace/project"})
    assert not rule.evaluate({"path": "/tmp/random"})


def test_rule_match_startswith():
    rule = Rule("test", {"path": {"$startswith": "/home"}}, "allow", 50)
    assert rule.evaluate({"path": "/home/user/project"})
    assert not rule.evaluate({"path": "/tmp/file"})


def test_rule_match_endswith():
    rule = Rule("test", {"filename": {"$endswith": ".py"}}, "allow", 50)
    assert rule.evaluate({"filename": "main.py"})
    assert not rule.evaluate({"filename": "main.go"})


def test_rule_match_exists_true():
    rule = Rule("test", {"user_id": {"$exists": True}}, "allow", 50)
    assert rule.evaluate({"user_id": "abc"})
    assert not rule.evaluate({"not_user": "abc"})


def test_rule_match_exists_false():
    rule = Rule("test", {"optional_field": {"$exists": False}}, "allow", 50)
    assert rule.evaluate({"user_id": "abc"})
    assert not rule.evaluate({"optional_field": "present"})


def test_rule_match_neq():
    rule = Rule("test", {"role": {"$neq": "admin"}}, "allow", 50)
    assert rule.evaluate({"role": "user"})
    assert not rule.evaluate({"role": "admin"})


def test_rule_match_pattern():
    rule = Rule("test", {"match": {"field": "email", "pattern": r".+@.+\..+"}}, "allow", 50)
    assert rule.evaluate({"email": "test@example.com"})
    assert not rule.evaluate({"email": "invalid"})


def test_rule_complex_nested():
    rule = Rule(
        "test",
        {
            "and": [
                {"role": {"$in": ["admin", "moderator"]}},
                {"action": "delete"},
                {
                    "or": [
                        {"resource": "users"},
                        {"resource": "posts"},
                    ]
                },
            ]
        },
        "allow",
        100,
    )
    assert rule.evaluate({"role": "admin", "action": "delete", "resource": "users"})
    assert rule.evaluate({"role": "moderator", "action": "delete", "resource": "posts"})
    assert not rule.evaluate({"role": "user", "action": "delete", "resource": "users"})
    assert not rule.evaluate({"role": "admin", "action": "view", "resource": "users"})


def test_rule_default_match_all():
    rule = Rule("default-deny", {}, "deny", 0)
    assert rule.evaluate({"anything": "value"})
    assert rule.evaluate({})


def test_rule_dot_path_resolution():
    rule = Rule("test", {"args.path": {"$contains": "/workspace/"}}, "allow", 50)
    assert rule.evaluate({"args": {"path": "/workspace/project/file.txt"}})
    assert not rule.evaluate({"args": {"path": "/tmp/file.txt"}})


# ─── Rule.trace ──────────────────────────────────────────────────────


def test_rule_trace_matched():
    rule = Rule("deny-exec", {"tool": "exec"}, "deny", 100)
    matched, trace = rule.evaluate_traced({"tool": "exec"})
    assert matched
    assert trace.rule_name == "deny-exec"
    assert trace.effect == "deny"
    assert len(trace.steps) > 0
    last = trace.steps[-1]
    assert last.result is True


def test_rule_trace_not_matched():
    rule = Rule("deny-exec", {"tool": "exec"}, "deny", 100)
    matched, trace = rule.evaluate_traced({"tool": "ping"})
    assert not matched
    assert len(trace.steps) > 0
    last = trace.steps[-1]
    assert last.result is False


def test_rule_trace_complex():
    rule = Rule(
        "complex",
        {
            "and": [
                {"role": "admin"},
                {"or": [{"tool": "delete"}, {"tool": "create"}]},
            ]
        },
        "allow",
        100,
    )
    matched, trace = rule.evaluate_traced({"role": "admin", "tool": "delete"})
    assert matched
    assert len(trace.steps) >= 1
    root = trace.steps[0]
    assert root.condition.op == Op.AND
    assert len(root.children) >= 2


# ─── RuleSet ─────────────────────────────────────────────────────────


def test_ruleset_priority():
    rs = RuleSet(
        [
            Rule("allow-all", {}, "allow", 0),
            Rule("deny-exec", {"tool": "exec"}, "deny", 100),
        ]
    )
    effect, name = rs.evaluate({"tool": "exec"})
    assert effect == "deny"
    assert name == "deny-exec"


def test_ruleset_priority_allow():
    rs = RuleSet(
        [
            Rule("deny-exec", {"tool": "exec"}, "deny", 100),
            Rule("allow-specific", {"tool": "exec", "role": "admin"}, "allow", 200),
        ]
    )
    effect, name = rs.evaluate({"tool": "exec", "role": "admin"})
    assert effect == "allow"
    assert name == "allow-specific"


def test_ruleset_no_match():
    rs = RuleSet(
        [
            Rule("deny-exec", {"tool": "exec"}, "deny", 100),
        ]
    )
    effect, name = rs.evaluate({"tool": "ping"})
    assert effect is None
    assert name is None


def test_ruleset_disabled_rule():
    rs = RuleSet(
        [
            Rule("deny-exec", {"tool": "exec"}, "deny", 100, enabled=False),
            Rule("allow-all", {}, "allow", 0),
        ]
    )
    effect, name = rs.evaluate({"tool": "exec"})
    assert effect == "allow"
    assert name == "allow-all"


def test_ruleset_add_rule():
    rs = RuleSet([Rule("deny-exec", {"tool": "exec"}, "deny", 100)])
    rs.add_rule(Rule("allow-all", {}, "allow", 0))
    assert rs.rules[0].name == "deny-exec"
    assert rs.rules[1].name == "allow-all"


# ─── RuleSet.evaluate_detailed ───────────────────────────────────────


def test_ruleset_evaluate_detailed_match():
    rs = RuleSet(
        [
            Rule("deny-exec", {"tool": "exec"}, "deny", 100),
            Rule("allow-all", {}, "allow", 0),
        ]
    )
    decision = rs.evaluate_detailed({"tool": "exec"})
    assert decision.effect == "deny"
    assert decision.rule_name == "deny-exec"
    assert decision.trace is not None
    assert len(decision.trace) >= 1


def test_ruleset_evaluate_detailed_no_match():
    rs = RuleSet(
        [
            Rule("deny-exec", {"tool": "exec"}, "deny", 100),
        ]
    )
    decision = rs.evaluate_detailed({"tool": "ping"})
    assert decision.effect is None
    assert decision.rule_name is None
    assert decision.trace is not None


def test_ruleset_evaluate_detailed_disabled_rule_skipped():
    rs = RuleSet(
        [
            Rule("deny-exec", {"tool": "exec"}, "deny", 100, enabled=False),
            Rule("allow-all", {}, "allow", 0),
        ]
    )
    decision = rs.evaluate_detailed({"tool": "exec"})
    assert decision.effect == "allow"
    assert decision.rule_name == "allow-all"


# ─── PolicyEngine ────────────────────────────────────────────────────


def test_policy_engine_load_json():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(
            {
                "rules": [
                    {"name": "deny-exec", "condition": {"tool": "exec"}, "effect": "deny", "priority": 100},
                ],
            },
            f,
        )
        f.flush()
        engine = PolicyEngine()
        rs = engine.load_ruleset("test", f.name)
        assert rs is not None
        effect, name = rs.evaluate({"tool": "exec"})
        assert effect == "deny"
    os.unlink(f.name)


def test_policy_engine_load_json_with_all_fields():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(
            {
                "rules": [
                    {
                        "name": "complex-rule",
                        "condition": {"role": {"$in": ["admin", "moderator"]}},
                        "effect": "allow",
                        "priority": 50,
                        "description": "Allow admins and moderators",
                        "tags": ["admin", "moderator"],
                        "enabled": True,
                        "metadata": {"source": "config"},
                    },
                ],
            },
            f,
        )
        f.flush()
        engine = PolicyEngine()
        rs = engine.load_ruleset("test", f.name)
        assert rs is not None
        assert rs.rules[0].name == "complex-rule"
        assert rs.rules[0].description == "Allow admins and moderators"
        assert rs.rules[0].tags == ["admin", "moderator"]
        assert rs.rules[0].enabled is True
    os.unlink(f.name)


def test_policy_engine_load_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("rules:\n")
        f.write("  - name: deny-exec\n")
        f.write("    condition:\n")
        f.write("      tool: exec\n")
        f.write("    effect: deny\n")
        f.write("    priority: 100\n")
        f.flush()
        engine = PolicyEngine()
        rs = engine.load_ruleset("test", f.name)
        assert rs is not None
        effect, name = rs.evaluate({"tool": "exec"})
        assert effect == "deny"
    os.unlink(f.name)


def test_policy_engine_check():
    engine = PolicyEngine()
    rs = RuleSet([Rule("deny-exec", {"tool": "exec"}, "deny", 100)])
    engine._rulesets["tools"] = rs
    assert not engine.check("tools", {"tool": "exec"})
    assert engine.check("tools", {"tool": "ping"})


def test_policy_engine_missing_ruleset():
    engine = PolicyEngine()
    result = engine.get_ruleset("nonexistent")
    assert result is None


def test_policy_engine_evaluate_detailed():
    engine = PolicyEngine()
    rs = RuleSet([Rule("deny-exec", {"tool": "exec"}, "deny", 100)])
    engine._rulesets["tools"] = rs
    decision = engine.evaluate_detailed("tools", {"tool": "exec"})
    assert decision.effect == "deny"
    assert decision.rule_name == "deny-exec"
    assert decision.trace is not None


def test_policy_engine_watcher():
    engine = PolicyEngine()
    engine.start_watcher(interval=0.5)
    assert engine._watcher_active
    engine.stop_watcher()
    assert not engine._watcher_active


def test_parse_simple():
    engine = PolicyEngine()
    rules = engine._parse_simple("deny-exec: deny tool.*exec")
    assert len(rules) >= 1
    assert rules[0].effect == "deny"


def test_policy_engine_to_dict():
    engine = PolicyEngine()
    rs = RuleSet([Rule("deny-exec", {"tool": "exec"}, "deny", 100)], name="tools")
    engine._rulesets["tools"] = rs
    d = engine.to_dict()
    assert "tools" in d
    assert d["tools"][0]["name"] == "deny-exec"
    assert d["tools"][0]["effect"] == "deny"


def test_rule_to_dict():
    rule = Rule("deny-exec", {"tool": "exec"}, "deny", 100, description="Blocks exec", tags=["security"])
    d = rule.to_dict()
    assert d["name"] == "deny-exec"
    assert d["effect"] == "deny"
    assert d["priority"] == 100
    assert d["description"] == "Blocks exec"
    assert d["tags"] == ["security"]
    assert d["enabled"] is True


def test_ruleset_to_dict():
    rs = RuleSet([Rule("deny-exec", {"tool": "exec"}, "deny", 100)])
    d = rs.to_dict()
    assert len(d) == 1
    assert d[0]["name"] == "deny-exec"


def test_condition_node_repr():
    node = ConditionNode(Op.TRUE)
    assert repr(node) == "TRUE"

    node2 = ConditionNode(Op.EQ, path="tool", value="exec")
    assert "tool" in repr(node2)
    assert "eq" in repr(node2)

    node3 = ConditionNode(Op.AND, children=[ConditionNode(Op.TRUE)])
    assert "AND" in repr(node3)


def test_rule_evaluate_exception_safe():
    class ExplodingDict(dict):  # type: ignore[type-arg]
        def get(self, key, default=None):
            raise RuntimeError("boom")

    rule = Rule("safe", {"tool": "exec"}, "deny", 100)
    assert not rule.evaluate(ExplodingDict())

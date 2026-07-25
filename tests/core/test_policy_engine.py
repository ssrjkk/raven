from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

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
        effect, _name = rs.evaluate({"tool": "exec"})
        assert effect == "deny"
    Path(f.name).unlink()


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
    Path(f.name).unlink()


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
        effect, _name = rs.evaluate({"tool": "exec"})
        assert effect == "deny"
    Path(f.name).unlink()


def test_policy_engine_check():
    engine = PolicyEngine()
    rs = RuleSet([
        Rule("deny-exec", {"tool": "exec"}, "deny", 100),
        Rule("allow-ping", {"tool": "ping"}, "allow", 50),
    ])
    engine._rulesets["tools"] = rs
    assert not engine.check("tools", {"tool": "exec"})
    assert engine.check("tools", {"tool": "ping"})
    assert not engine.check("tools", {"tool": "unknown-tool"})


def test_policy_engine_missing_ruleset():
    engine = PolicyEngine()
    result = engine.get_ruleset("nonexistent")
    assert result is None





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


# ─── Adversarial acceptance tests (Шаг 1-4) ────────────────────────


class TestAdversarialNamespacePolicy:
    """Шаг 1+4: prove namespaced tool names are blocked by policy engine."""

    def test_deny_ruleset_blocks_namespaced_sessions_spawn(self):
        engine = PolicyEngine()
        rs = engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        assert rs is not None
        assert len(rs.rules) > 0
        assert not engine.check("tools", {"tool": "sessions.sessions_spawn", "profile": "full", "action": "call"})

    def test_deny_ruleset_blocks_namespaced_api_http_post(self):
        engine = PolicyEngine()
        engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        assert not engine.check("tools", {"tool": "api.http_post", "profile": "full", "action": "call"})

    def test_deny_ruleset_blocks_namespaced_process_kill(self):
        engine = PolicyEngine()
        engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        assert not engine.check("tools", {"tool": "process.kill", "profile": "full", "action": "call"})

    def test_old_non_namespaced_names_not_in_deny_rules(self):
        engine = PolicyEngine()
        engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        rs = engine.get_ruleset("tools")
        assert rs is not None
        all_conditions = []
        for rule in rs.rules:
            d = rule._condition.__dict__
            if d.get("op") == Op.OR:
                for child in d.get("children", []):
                    if hasattr(child, "value"):
                        all_conditions.append(child.value)
            elif hasattr(rule._condition, "value"):
                all_conditions.append(rule._condition.value)
        assert "sessions_spawn" not in all_conditions, "Old non-namespaced 'sessions_spawn' still in rules"
        assert "shell.exec" not in all_conditions, "Old non-namespaced 'shell.exec' still in rules"

    def test_deny_by_default_no_explicit_allow(self):
        engine = PolicyEngine()
        engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        assert not engine.check("tools", {"tool": "totally-unknown-tool", "profile": "full", "action": "call"})

    def test_allow_messaging_profile_access_files_read(self):
        engine = PolicyEngine()
        engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        assert engine.check("tools", {"tool": "files.read", "profile": "messaging", "action": "call"})

    def test_allow_messaging_profile_access_memory_recall(self):
        engine = PolicyEngine()
        engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        assert engine.check("tools", {"tool": "memory.recall", "profile": "messaging", "action": "call"})


class TestAdversarialToolPolicyDenyByDefault:
    """Шаг 3: prove ToolPolicyEvaluator denies unknown tools by default with policy engine."""

    @pytest.mark.asyncio
    async def test_exec_security_deny_refuses_every_tool(self):
        from raven.core.security.tool_policy import ExecSecurity, ToolPolicyEvaluator

        p = ToolPolicyEvaluator(exec_security=ExecSecurity.DENY)
        for tool in ["process.run", "process.kill", "git.git_push", "sessions.sessions_spawn"]:
            allowed, _reason = await p.check_exec(tool)
            assert not allowed, f"Expected deny for {tool}, got allowed={allowed}"

    def test_profile_full_allows_unknown_tools_but_deny_list_still_blocks(self):
        from raven.core.security.tool_policy import ExecSecurity, ToolPolicyEvaluator

        p = ToolPolicyEvaluator(
            profile="full",
            deny=["process.kill", "sessions.sessions_spawn"],
            exec_security=ExecSecurity.FULL,
        )
        assert not p.is_tool_allowed("process.kill")
        assert not p.is_tool_allowed("sessions.sessions_spawn")
        assert p.is_tool_allowed("process.run")


class TestAdversarialConfirmationBlocksExecution:
    """Шаг 2: prove confirm=True blocks tool execution when user declines."""

    @pytest.mark.asyncio
    async def test_confirm_blocks_when_user_declines(self):
        from unittest.mock import AsyncMock

        from raven.core.security.tool_policy import ExecAskMode, ExecSecurity, ToolPolicyEvaluator

        confirm_fn = AsyncMock(return_value=False)
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK, exec_ask=ExecAskMode.ALWAYS)
        allowed, reason = await p.check_exec("process.kill", {}, confirm_fn=confirm_fn)
        assert not allowed
        assert "cancelled" in (reason or "").lower()
        confirm_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_passes_when_user_approves(self):
        from unittest.mock import AsyncMock

        from raven.core.security.tool_policy import ExecAskMode, ExecSecurity, ToolPolicyEvaluator

        confirm_fn = AsyncMock(return_value=True)
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK, exec_ask=ExecAskMode.ALWAYS)
        allowed, _reason = await p.check_exec("process.kill", {}, confirm_fn=confirm_fn)
        assert allowed
        confirm_fn.assert_called_once()


class TestAdversarialBudgetExceeded:
    """Шаг 7: prove budget tracker denies when limit exceeded."""

    @pytest.mark.asyncio
    async def test_budget_denies_when_limit_exceeded(self):
        from raven.core.budget import TokenBudgetTracker

        tracker = TokenBudgetTracker()
        allowed = await tracker.check_budget("user1", 400_000, 0, 500_000, 3600)
        assert allowed
        allowed = await tracker.check_budget("user1", 200_000, 0, 500_000, 3600)
        assert not allowed

    @pytest.mark.asyncio
    async def test_budget_allows_different_users_independently(self):
        from raven.core.budget import TokenBudgetTracker

        tracker = TokenBudgetTracker()
        allowed = await tracker.check_budget("user_a", 400_000, 0, 500_000, 3600)
        assert allowed
        allowed = await tracker.check_budget("user_b", 400_000, 0, 500_000, 3600)
        assert allowed

    @pytest.mark.asyncio
    async def test_budget_load_test_59_msgs_40k_tokens(self):
        from raven.core.budget import TokenBudgetTracker

        tracker = TokenBudgetTracker()
        denied_at = None
        for i in range(59):
            allowed = await tracker.check_budget("load_user", 40_000, 0, 500_000, 3600)
            if not allowed:
                denied_at = i + 1
                break
        assert denied_at is not None, "Budget should have been exceeded"
        assert denied_at == 13, f"Expected denial at msg 13 (13*40k=520k > 500k), got {denied_at}"


class TestAdversarialIntegrationSpy:
    """Доказательство 3: spy on policy_engine.check() proves deny reaches engine.

    We must NOT put the target tool in the local deny list, otherwise
    is_tool_allowed() short-circuits before reaching policy_engine.check().
    Instead, we rely solely on the tools.json deny rules.
    """

    def test_process_run_denied_via_policy_engine_evaluate_spy(self):
        from unittest.mock import patch

        from raven.core.security.policy_engine import policy_engine
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        policy_engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))
        rs = policy_engine.get_ruleset("tools")
        assert rs is not None and len(rs.rules) > 0

        eval_calls: list[dict[str, object]] = []
        original_eval = policy_engine.__class__.evaluate

        def spy_evaluate(self, ruleset_name, input_data):
            result = original_eval(self, ruleset_name, input_data)
            eval_calls.append({"ruleset": ruleset_name, "input": input_data, "result": result})
            return result

        with patch.object(type(policy_engine), "evaluate", spy_evaluate):
            p = ToolPolicyEvaluator(profile="full")
            allowed = p.is_tool_allowed("process.run")
            assert not allowed, "process.run should be denied by policy engine"
            tool_calls = [c for c in eval_calls if c["input"].get("tool") == "process.run"]
            assert len(tool_calls) >= 1, "policy_engine.evaluate was never called for process.run"
            effect, _ = tool_calls[-1]["result"]
            assert effect == "deny"

    def test_git_push_denied_via_policy_engine_evaluate_spy(self):
        from unittest.mock import patch

        from raven.core.security.policy_engine import policy_engine
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        policy_engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))

        eval_calls: list[dict[str, object]] = []
        original_eval = policy_engine.__class__.evaluate

        def spy_evaluate(self, ruleset_name, input_data):
            result = original_eval(self, ruleset_name, input_data)
            eval_calls.append({"ruleset": ruleset_name, "input": input_data, "result": result})
            return result

        with patch.object(type(policy_engine), "evaluate", spy_evaluate):
            p = ToolPolicyEvaluator(profile="full")
            allowed = p.is_tool_allowed("git.git_push")
            assert not allowed
            tool_calls = [c for c in eval_calls if c["input"].get("tool") == "git.git_push"]
            assert len(tool_calls) >= 1
            effect, _ = tool_calls[-1]["result"]
            assert effect == "deny"

    def test_sessions_spawn_denied_via_policy_engine_evaluate_spy(self):
        from unittest.mock import patch

        from raven.core.security.policy_engine import policy_engine
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        policy_engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))

        eval_calls: list[dict[str, object]] = []
        original_eval = policy_engine.__class__.evaluate

        def spy_evaluate(self, ruleset_name, input_data):
            result = original_eval(self, ruleset_name, input_data)
            eval_calls.append({"ruleset": ruleset_name, "input": input_data, "result": result})
            return result

        with patch.object(type(policy_engine), "evaluate", spy_evaluate):
            p = ToolPolicyEvaluator(profile="full")
            allowed = p.is_tool_allowed("sessions.sessions_spawn")
            assert not allowed
            tool_calls = [c for c in eval_calls if c["input"].get("tool") == "sessions.sessions_spawn"]
            assert len(tool_calls) >= 1
            effect, _ = tool_calls[-1]["result"]
            assert effect == "deny"

    def test_process_kill_denied_via_policy_engine_evaluate_spy(self):
        from unittest.mock import patch

        from raven.core.security.policy_engine import policy_engine
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        policy_engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))

        eval_calls: list[dict[str, object]] = []
        original_eval = policy_engine.__class__.evaluate

        def spy_evaluate(self, ruleset_name, input_data):
            result = original_eval(self, ruleset_name, input_data)
            eval_calls.append({"ruleset": ruleset_name, "input": input_data, "result": result})
            return result

        with patch.object(type(policy_engine), "evaluate", spy_evaluate):
            p = ToolPolicyEvaluator(profile="full")
            allowed = p.is_tool_allowed("process.kill")
            assert not allowed
            tool_calls = [c for c in eval_calls if c["input"].get("tool") == "process.kill"]
            assert len(tool_calls) >= 1
            effect, _ = tool_calls[-1]["result"]
            assert effect == "deny"

    def test_process_run_python_denied_via_policy_engine_evaluate_spy(self):
        from unittest.mock import patch

        from raven.core.security.policy_engine import policy_engine
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        policy_engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))

        eval_calls: list[dict[str, object]] = []
        original_eval = policy_engine.__class__.evaluate

        def spy_evaluate(self, ruleset_name, input_data):
            result = original_eval(self, ruleset_name, input_data)
            eval_calls.append({"ruleset": ruleset_name, "input": input_data, "result": result})
            return result

        with patch.object(type(policy_engine), "evaluate", spy_evaluate):
            p = ToolPolicyEvaluator(profile="full")
            allowed = p.is_tool_allowed("process.run_python")
            assert not allowed
            tool_calls = [c for c in eval_calls if c["input"].get("tool") == "process.run_python"]
            assert len(tool_calls) >= 1
            effect, _ = tool_calls[-1]["result"]
            assert effect == "deny"

    def test_git_pull_denied_via_policy_engine_evaluate_spy(self):
        from unittest.mock import patch

        from raven.core.security.policy_engine import policy_engine
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        policy_engine.load_ruleset("tools", str(Path(__file__).resolve().parent.parent.parent / "policy" / "tools.json"))

        eval_calls: list[dict[str, object]] = []
        original_eval = policy_engine.__class__.evaluate

        def spy_evaluate(self, ruleset_name, input_data):
            result = original_eval(self, ruleset_name, input_data)
            eval_calls.append({"ruleset": ruleset_name, "input": input_data, "result": result})
            return result

        with patch.object(type(policy_engine), "evaluate", spy_evaluate):
            p = ToolPolicyEvaluator(profile="full")
            allowed = p.is_tool_allowed("git.git_pull")
            assert not allowed
            tool_calls = [c for c in eval_calls if c["input"].get("tool") == "git.git_pull"]
            assert len(tool_calls) >= 1
            effect, _ = tool_calls[-1]["result"]
            assert effect == "deny"

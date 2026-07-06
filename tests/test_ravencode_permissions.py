from __future__ import annotations

from ravencode.runtime.permissions import PermissionAction, PermissionManager, PermissionRule, default_deny_rules


class TestPermissionRule:
    def test_creates_with_tool_and_action(self):
        r = PermissionRule(tool="bash", action=PermissionAction.DENY, reason="no shell")
        assert r.tool == "bash"
        assert r.action == PermissionAction.DENY
        assert r.reason == "no shell"

    def test_default_reason_empty(self):
        r = PermissionRule(tool="read", action=PermissionAction.ALLOW)
        assert r.reason == ""


class TestPermissionManager:
    def test_empty_allows_by_default(self):
        pm = PermissionManager()
        allowed, reason = pm.is_allowed("bash")
        assert allowed is True
        assert reason == ""

    def test_deny_blocklist(self):
        pm = PermissionManager()
        pm.deny("bash", "blocked")
        allowed, reason = pm.is_allowed("bash")
        assert allowed is False
        assert "blocked" in reason

    def test_allow_overrides_deny(self):
        pm = PermissionManager()
        pm.deny("bash")
        pm.allow("bash")
        allowed, _ = pm.is_allowed("bash")
        assert allowed is True

    def test_last_rule_wins(self):
        pm = PermissionManager()
        pm.allow("bash")
        pm.deny("bash")
        allowed, _ = pm.is_allowed("bash")
        assert allowed is False

    def test_wildcard_deny_blocks_all(self):
        pm = PermissionManager()
        pm.deny("*", "locked down")
        assert pm.is_allowed("bash")[0] is False
        assert pm.is_allowed("write")[0] is False
        assert pm.is_allowed("read")[0] is False

    def test_wildcard_allow_allows_all(self):
        pm = PermissionManager()
        pm.deny("*")
        pm.allow("*")
        assert pm.is_allowed("anything")[0] is True

    def test_rules_property_returns_copy(self):
        pm = PermissionManager()
        pm.deny("bash")
        rules = pm.rules
        rules.clear()
        assert len(pm.rules) == 1

    def test_add_rule(self):
        pm = PermissionManager()
        pm.add_rule(PermissionRule(tool="bash", action=PermissionAction.DENY))
        assert pm.is_allowed("bash")[0] is False

    def test_to_dict(self):
        pm = PermissionManager()
        pm.deny("bash", "no shell")
        pm.allow("read")
        d = pm.to_dict()
        assert len(d) == 2
        assert d[0] == {"tool": "bash", "action": "deny", "reason": "no shell"}
        assert d[1] == {"tool": "read", "action": "allow", "reason": ""}

    def test_constructor_with_rules(self):
        rules = [PermissionRule(tool="write", action=PermissionAction.DENY)]
        pm = PermissionManager(rules=rules)
        assert pm.is_allowed("write")[0] is False
        assert pm.is_allowed("read")[0] is True

    def test_unknown_tool_allowed_by_default(self):
        pm = PermissionManager()
        allowed, _ = pm.is_allowed("nonexistent_tool")
        assert allowed is True


class TestDefaultDenyRules:
    def test_contains_dangerous_tools(self):
        rules = default_deny_rules()
        tool_names = [r.tool for r in rules]
        assert "bash" in tool_names
        assert "write" in tool_names
        assert "edit" in tool_names
        assert "git_commit" in tool_names
        assert "git_add" in tool_names
        assert "task" in tool_names

    def test_all_are_deny(self):
        rules = default_deny_rules()
        assert all(r.action == PermissionAction.DENY for r in rules)

    def test_all_have_reason(self):
        rules = default_deny_rules()
        assert all(len(r.reason) > 0 for r in rules)

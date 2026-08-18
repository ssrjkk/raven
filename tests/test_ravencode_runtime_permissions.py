from __future__ import annotations

from ravencode.runtime.permissions import (
    PermissionAction,
    PermissionManager,
    PermissionRule,
    default_deny_rules,
)


class TestPermissionRule:
    def test_defaults(self) -> None:
        rule = PermissionRule(tool="bash", action=PermissionAction.DENY)
        assert rule.reason == ""

    def test_fields(self) -> None:
        rule = PermissionRule(tool="bash", action=PermissionAction.ALLOW, reason="ok")
        assert rule.tool == "bash"
        assert rule.action == PermissionAction.ALLOW
        assert rule.reason == "ok"


class TestPermissionManager:
    def test_default_action_allows(self) -> None:
        mgr = PermissionManager()
        assert mgr.is_allowed("anything") == (True, "")

    def test_rules_property_returns_copy(self) -> None:
        mgr = PermissionManager([PermissionRule("a", PermissionAction.DENY)])
        rules = mgr.rules
        rules.append(PermissionRule("b", PermissionAction.DENY))
        assert len(mgr.rules) == 1

    def test_add_rule(self) -> None:
        mgr = PermissionManager()
        mgr.add_rule(PermissionRule("x", PermissionAction.DENY, "no"))
        assert mgr.is_allowed("x") == (False, "no")

    def test_allow(self) -> None:
        mgr = PermissionManager()
        mgr.deny("bash")
        mgr.allow("bash", reason="user approved")
        assert mgr.is_allowed("bash") == (True, "")

    def test_deny(self) -> None:
        mgr = PermissionManager()
        mgr.deny("bash")
        assert mgr.is_allowed("bash") == (False, "tool 'bash' denied by permission rule")

    def test_deny_with_reason(self) -> None:
        mgr = PermissionManager()
        mgr.deny("bash", reason="read-only")
        assert mgr.is_allowed("bash") == (False, "read-only")

    def test_wildcard_rule(self) -> None:
        mgr = PermissionManager([PermissionRule("*", PermissionAction.DENY, "lockdown")])
        assert mgr.is_allowed("anything") == (False, "lockdown")

    def test_latest_rule_wins(self) -> None:
        mgr = PermissionManager()
        mgr.allow("bash")
        mgr.deny("bash")
        assert mgr.is_allowed("bash") == (False, "tool 'bash' denied by permission rule")

    def test_rule_order_reversed(self) -> None:
        mgr = PermissionManager([PermissionRule("bash", PermissionAction.DENY, "first"), PermissionRule("*", PermissionAction.ALLOW)])
        assert mgr.is_allowed("bash") == (True, "")

    def test_to_dict(self) -> None:
        mgr = PermissionManager([PermissionRule("bash", PermissionAction.DENY, "r")])
        assert mgr.to_dict() == [{"tool": "bash", "action": "deny", "reason": "r"}]

    def test_from_dict(self) -> None:
        mgr = PermissionManager.from_dict([{"tool": "write", "action": "deny", "reason": "ro"}])
        assert mgr.is_allowed("write") == (False, "ro")

    def test_from_dict_invalid_action_denies(self) -> None:
        mgr = PermissionManager.from_dict([{"tool": "bash", "action": "maybe"}])
        assert mgr.is_allowed("bash") == (False, "tool 'bash' denied by permission rule")

    def test_from_dict_missing_fields(self) -> None:
        mgr = PermissionManager.from_dict([{"action": "allow"}])
        assert mgr.is_allowed("anything") == (True, "")


class TestDefaultDenyRules:
    def test_denies_dangerous_tools(self) -> None:
        rules = default_deny_rules()
        mgr = PermissionManager(rules=rules)
        for tool in ("bash", "write", "edit", "git_commit", "git_add", "task"):
            assert mgr.is_allowed(tool)[0] is False

    def test_allows_other_tools(self) -> None:
        mgr = PermissionManager(rules=default_deny_rules())
        assert mgr.is_allowed("read") == (True, "")

from __future__ import annotations

import pytest

from ravencode.runtime.permissions import PermissionAction, PermissionManager, PermissionRule


class TestPermissionManagerFromDict:
    def test_from_dict_empty(self):
        pm = PermissionManager.from_dict([])
        assert pm.rules == []

    def test_from_dict_single_deny(self):
        pm = PermissionManager.from_dict([
            {"tool": "bash", "action": "deny", "reason": "no shell"},
        ])
        allowed, reason = pm.is_allowed("bash")
        assert allowed is False
        assert "no shell" in reason

    def test_from_dict_multiple(self):
        pm = PermissionManager.from_dict([
            {"tool": "bash", "action": "deny"},
            {"tool": "write", "action": "deny"},
            {"tool": "read", "action": "allow"},
        ])
        assert pm.is_allowed("bash")[0] is False
        assert pm.is_allowed("write")[0] is False
        assert pm.is_allowed("read")[0] is True

    def test_from_dict_wildcard(self):
        pm = PermissionManager.from_dict([
            {"tool": "*", "action": "deny", "reason": "locked"},
        ])
        assert pm.is_allowed("anything")[0] is False

    def test_from_dict_invalid_action_falls_back_to_deny(self):
        pm = PermissionManager.from_dict([
            {"tool": "bash", "action": "invalid", "reason": "bad"},
        ])
        allowed, _ = pm.is_allowed("bash")
        assert allowed is False

    def test_from_dict_roundtrip(self):
        original = PermissionManager()
        original.deny("bash", "no shell")
        original.allow("read")
        d = original.to_dict()
        restored = PermissionManager.from_dict(d)
        assert restored.is_allowed("bash")[0] is False
        assert restored.is_allowed("read")[0] is True

    def test_allow_method(self):
        pm = PermissionManager()
        pm.allow("read")
        allowed, _ = pm.is_allowed("read")
        assert allowed is True

    def test_deny_method(self):
        pm = PermissionManager()
        pm.deny("bash", "forbidden")
        allowed, reason = pm.is_allowed("bash")
        assert allowed is False
        assert "forbidden" in reason

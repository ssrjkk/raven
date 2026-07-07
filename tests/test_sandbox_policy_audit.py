from __future__ import annotations

import pytest

from raven.core.security.sandbox_policy import (
    MAIN_SESSION_POLICY,
    NON_MAIN_SESSION_POLICY,
    CODE_EXECUTION_POLICY,
    check_tool_allowed,
    check_path_allowed,
    get_policy,
    get_policy_for_channel,
)


class TestSandboxPolicy:
    def test_check_tool_allowed_allows_known_tool(self):
        ok, msg = check_tool_allowed(MAIN_SESSION_POLICY, "file.read")
        assert ok
        assert msg == ""

    def test_check_tool_allowed_denies_restricted_tool(self):
        ok, msg = check_tool_allowed(NON_MAIN_SESSION_POLICY, "browser_open")
        assert not ok
        assert "not allowed" in msg or "denied" in msg

    def test_check_tool_allowed_denies_not_in_allowlist(self):
        ok, msg = check_tool_allowed(CODE_EXECUTION_POLICY, "canvas_render")
        assert not ok
        assert "not allowed" in msg

    def test_check_tool_allowed_with_channel_logging(self):
        ok, msg = check_tool_allowed(NON_MAIN_SESSION_POLICY, "browser_open", channel="test_ch")
        assert not ok

    def test_check_path_allowed_no_restrictions(self):
        ok, msg = check_path_allowed(MAIN_SESSION_POLICY, "/any/path")
        assert ok

    def test_check_path_allowed_with_allow_read(self):
        policy = MAIN_SESSION_POLICY
        policy.allow_read = ["/allowed"]
        ok, msg = check_path_allowed(policy, "/allowed/file.txt")
        assert ok
        ok2, _ = check_path_allowed(policy, "/other/file.txt")
        assert not ok2

    def test_get_policy_returns_correct(self):
        assert get_policy("main") == MAIN_SESSION_POLICY
        assert get_policy("code-exec") == CODE_EXECUTION_POLICY
        assert get_policy("nonexistent").name == "non-main"

    def test_get_policy_for_channel_default(self):
        policy = get_policy_for_channel("telegram")
        assert policy.name == "main"

    def test_get_policy_for_channel_mapped(self, monkeypatch):
        monkeypatch.setattr("raven.core.config.settings.channel_sandbox_policy", '{"telegram": "non-main"}')
        policy = get_policy_for_channel("telegram")
        assert policy.name == "non-main"

    def test_get_policy_for_channel_unknown_channel(self, monkeypatch):
        monkeypatch.setattr("raven.core.config.settings.channel_sandbox_policy", '{"telegram": "non-main"}')
        policy = get_policy_for_channel("unknown")
        assert policy.name == "main"

    def test_get_policy_for_channel_invalid_json(self, monkeypatch):
        monkeypatch.setattr("raven.core.config.settings.channel_sandbox_policy", "bad-json")
        policy = get_policy_for_channel("telegram")
        assert policy.name == "main"

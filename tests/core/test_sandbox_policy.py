from __future__ import annotations

import pytest

from raven.core import config as config_module
from raven.core.security.sandbox_policy import (
    POLICY_REGISTRY,
    SandboxPolicy,
    check_path_allowed,
    check_tool_allowed,
    get_policy,
    get_policy_for_channel,
    session_type_to_policy,
)


class TestSandboxPolicy:
    def test_registry_has_main_policy(self):
        assert "main" in POLICY_REGISTRY

    def test_registry_has_code_exec_policy(self):
        assert "code-exec" in POLICY_REGISTRY

    def test_get_policy_default(self):
        policy = get_policy("main")
        assert isinstance(policy, SandboxPolicy)

    def test_get_policy_unknown_returns_non_main(self):
        policy = get_policy("nonexistent")
        assert policy.name == "non-main"

    def test_main_policy_allows_read(self):
        policy = get_policy("main")
        allowed, _ = check_tool_allowed(policy, "read")
        assert allowed is True

    def test_readonly_policy_denies_write(self):
        policy = get_policy("read-only")
        assert policy.denied_tools is not None
        assert "write" in policy.denied_tools

    def test_session_type_to_policy_returns_policy_object(self):
        policy = session_type_to_policy("main")
        assert isinstance(policy, SandboxPolicy)
        assert policy.name == "main"

    def test_session_type_to_policy_non_main(self):
        policy = session_type_to_policy("non-main")
        assert policy.name == "non-main"

    def test_allowed_tools_intersection(self):
        policy = get_policy("read-only")
        assert policy.allowed_tools is not None
        assert "read" in policy.allowed_tools
        assert "write" not in policy.allowed_tools


class TestCheckToolAllowed:
    def test_tool_not_in_allowlist_is_blocked(self):
        policy = get_policy("non-main")
        allowed, reason = check_tool_allowed(policy, "browser_open")
        assert allowed is False
        assert "not allowed" in reason

    def test_tool_in_denylist_is_blocked(self):
        policy = SandboxPolicy(name="custom", allowed_tools=None, denied_tools=["dangerous"])
        allowed, reason = check_tool_allowed(policy, "dangerous")
        assert allowed is False
        assert "denied" in reason

    def test_main_policy_allows_anything(self):
        policy = get_policy("main")
        allowed, _reason = check_tool_allowed(policy, "anything")
        assert allowed is True


class TestCheckPathAllowed:
    def test_no_allowlist_permits_everything(self):
        policy = SandboxPolicy(name="p")
        allowed, _ = check_path_allowed(policy, "/etc/passwd", "read")
        assert allowed is True

    def test_read_inside_allowed_dir(self, tmp_path):
        policy = SandboxPolicy(name="p", allow_read=[str(tmp_path)])
        allowed, _ = check_path_allowed(policy, str(tmp_path / "a.txt"), "read")
        assert allowed is True

    def test_read_outside_allowed_dir_denied(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        policy = SandboxPolicy(name="p", allow_read=[str(base)])
        allowed, reason = check_path_allowed(policy, str(tmp_path.parent / "escape.txt"), "read")
        assert allowed is False
        assert "not allowed" in reason

    def test_write_mode_uses_write_list(self, tmp_path):
        base = tmp_path / "w"
        base.mkdir()
        policy = SandboxPolicy(name="p", allow_write=[str(base)])
        allowed, _ = check_path_allowed(policy, str(base / "f.txt"), "write")
        assert allowed is True


class TestGetPolicyForChannel:
    def test_mapped_channel(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "channel_sandbox_policy", '{"telegram": "read-only"}')
        assert get_policy_for_channel("telegram").name == "read-only"

    def test_unmapped_channel_falls_back_to_main(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "channel_sandbox_policy", '{"telegram": "read-only"}')
        assert get_policy_for_channel("discord").name == "main"

    def test_unknown_policy_name_falls_back_to_main(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "channel_sandbox_policy", '{"telegram": "bogus"}')
        assert get_policy_for_channel("telegram").name == "main"

    def test_empty_config_falls_back_to_main(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "channel_sandbox_policy", "")
        assert get_policy_for_channel("telegram").name == "main"

    def test_bad_json_falls_back_to_main(self, monkeypatch):
        monkeypatch.setattr(config_module.settings, "channel_sandbox_policy", "not-json")
        assert get_policy_for_channel("telegram").name == "main"


class TestSessionTypeToPolicyBranches:
    def test_code_web_plan_and_default(self):
        assert session_type_to_policy("code").name == "code-exec"
        assert session_type_to_policy("web").name == "web-browsing"
        assert session_type_to_policy("plan").name == "read-only"
        assert session_type_to_policy("unknown").name == "non-main"

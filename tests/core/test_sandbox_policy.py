from __future__ import annotations

import pytest

from raven.core.security.sandbox_policy import (
    POLICY_REGISTRY,
    SandboxPolicy,
    check_tool_allowed,
    get_policy,
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
        assert "read" in policy.allowed_tools
        assert "write" not in policy.allowed_tools

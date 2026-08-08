from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.core.tools_rbac import ToolPolicyStore


def _spec(name: str, dangerous: bool = False, allowed_roles: list[str] | None = None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        handler=lambda **kw: f"ran:{name}",
        dangerous=dangerous,
        allowed_roles=allowed_roles,
    )


@pytest.fixture
def registry(tmp_path: Path) -> ToolRegistry:
    store = ToolPolicyStore(tmp_path / "tool_policy.json")
    reg = ToolRegistry(policy_store=store)
    reg.register(_spec("read_only"))
    reg.register(_spec("db_query", dangerous=True))
    reg.register(_spec("shell", dangerous=True, allowed_roles=["admin", "developer"]))
    return reg


class TestToolPolicyStore:
    def test_round_trip(self, tmp_path: Path):
        store = ToolPolicyStore(tmp_path / "tool_policy.json")
        store.set("shell", ["admin", "dev"])
        store.save()
        store2 = ToolPolicyStore(tmp_path / "tool_policy.json")
        assert store2.get("shell") == ["admin", "dev"]
        assert store2.get("missing") is None

    def test_remove(self, tmp_path: Path):
        store = ToolPolicyStore(tmp_path / "tool_policy.json")
        store.set("x", ["admin"])
        store.remove("x")
        assert store.get("x") is None

    def test_all(self, tmp_path: Path):
        store = ToolPolicyStore(tmp_path / "tool_policy.json")
        store.set("a", ["admin"])
        store.set("b", ["user"])
        assert store.all() == {"a": ["admin"], "b": ["user"]}


class TestRoleDefaults:
    def test_default_allows_all_roles(self, registry: ToolRegistry):
        assert registry.effective_allowed_roles("read_only") is None

    def test_dangerous_defaults_to_admin(self, registry: ToolRegistry):
        assert registry.effective_allowed_roles("db_query") == ["admin"]

    def test_explicit_roles_win(self, registry: ToolRegistry):
        assert registry.effective_allowed_roles("shell") == ["admin", "developer"]

    def test_policy_overrides_spec(self, registry: ToolRegistry):
        registry._policy.set("shell", ["operator"])
        assert registry.effective_allowed_roles("shell") == ["operator"]

    def test_unknown_tool_no_roles(self, registry: ToolRegistry):
        assert registry.effective_allowed_roles("nope") is None


class TestCallRbac:
    async def test_allowed_without_role(self, registry: ToolRegistry):
        assert await registry.call("db_query") == "ran:db_query"

    async def test_allowed_with_role(self, registry: ToolRegistry):
        assert await registry.call("db_query", role="admin") == "ran:db_query"

    async def test_denied_role(self, registry: ToolRegistry):
        result = await registry.call("db_query", role="user")
        assert result.startswith("[error]")
        assert "requires role" in result
        assert "db_query" in result

    async def test_denied_handler_not_invoked(self, registry: ToolRegistry):
        calls: list[dict[str, Any]] = []

        def handler(**kw: Any) -> str:
            calls.append(kw)
            return "ran"

        registry._tools["db_query"].handler = handler
        await registry.call("db_query", role="user")
        assert calls == []

    async def test_shell_allows_developer(self, registry: ToolRegistry):
        assert await registry.call("shell", role="developer") == "ran:shell"

    async def test_policy_override_grants_access(self, registry: ToolRegistry):
        registry._policy.set("db_query", ["user"])
        assert await registry.call("db_query", role="user") == "ran:db_query"

    async def test_no_role_never_denied(self, registry: ToolRegistry):
        assert await registry.call("shell") == "ran:shell"

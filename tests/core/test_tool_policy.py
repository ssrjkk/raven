from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest

import raven.core.security.policy_engine as policy_engine
from raven.core.security.tool_policy import (
    ExecAskMode,
    ExecSecurity,
    ToolPolicyEvaluator,
    resolve_within_root,
)


class TestResolveSafe:
    def test_empty_and_whitespace_return_none(self):
        assert resolve_within_root("") is None
        assert resolve_within_root("   ") is None

    def test_null_byte_returns_none(self):
        assert resolve_within_root("a\x00b") is None

    def test_resolve_error_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        def boom(self: Path, strict: bool = False) -> Path:
            raise OSError("unresolvable")

        monkeypatch.setattr(Path, "resolve", boom)
        assert resolve_within_root("some/path") is None

    def test_excessive_depth_returns_none(self):
        assert resolve_within_root("/" + "/".join(["x"] * 30)) is None

    def test_outside_root_returns_none(self, tmp_path: Path):
        assert resolve_within_root(str(tmp_path.parent / "escape"), tmp_path) is None


class TestSetWorkspaceRoot:
    def test_accepts_path_object(self, tmp_path: Path):
        p = ToolPolicyEvaluator()
        p.set_workspace_root(tmp_path)
        assert p._workspace_root is not None

    def test_accepts_string(self, tmp_path: Path):
        p = ToolPolicyEvaluator()
        p.set_workspace_root(str(tmp_path / "nested"))
        assert p._workspace_root is not None

    def test_invalid_root_raises_value_error(self):
        p = ToolPolicyEvaluator()
        with pytest.raises(ValueError, match="Invalid workspace root"):
            p.set_workspace_root("")


class TestImportFailureFallback:
    def test_is_tool_allowed_survives_import_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(sys.modules, "raven.core.security.policy_engine", None)
        p = ToolPolicyEvaluator(profile="messaging")
        assert p.is_tool_allowed("api.http_get") is True
        assert p.is_tool_allowed("shell.exec") is False

    async def test_check_exec_survives_import_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setitem(sys.modules, "raven.core.security.policy_engine", None)
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL)
        allowed, _reason = await p.check_exec("anything")
        assert allowed is True


class TestPolicyEngineDeny:
    async def test_check_exec_denied_by_policy_engine(self, monkeypatch: pytest.MonkeyPatch):
        class _RS:
            rules: ClassVar[list[object]] = [object()]

        monkeypatch.setattr(type(policy_engine), "get_ruleset", lambda self, name: _RS())
        monkeypatch.setattr(type(policy_engine), "check", lambda self, *a, **k: False)
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL)
        allowed, reason = await p.check_exec("evil")
        assert allowed is False
        assert "policy engine" in (reason or "")

    async def test_check_exec_allowed_by_policy_engine(self, monkeypatch: pytest.MonkeyPatch):
        class _RS:
            rules: ClassVar[list[object]] = [object()]

        monkeypatch.setattr(type(policy_engine), "get_ruleset", lambda self, name: _RS())
        monkeypatch.setattr(type(policy_engine), "check", lambda self, *a, **k: True)
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL)
        allowed, _reason = await p.check_exec("good")
        assert allowed is True

    def test_is_tool_allowed_denied_by_policy_engine(self, monkeypatch: pytest.MonkeyPatch):
        class _RS:
            rules: ClassVar[list[object]] = [object()]

        monkeypatch.setattr(type(policy_engine), "get_ruleset", lambda self, name: _RS())
        monkeypatch.setattr(type(policy_engine), "evaluate", lambda self, *a, **k: ("deny", None))
        p = ToolPolicyEvaluator(profile="full")
        assert p.is_tool_allowed("anything") is False

    def test_is_tool_allowed_policy_engine_allows(self, monkeypatch: pytest.MonkeyPatch):
        class _RS:
            rules: ClassVar[list[object]] = [object()]

        monkeypatch.setattr(type(policy_engine), "get_ruleset", lambda self, name: _RS())
        monkeypatch.setattr(type(policy_engine), "evaluate", lambda self, *a, **k: ("allow", None))
        p = ToolPolicyEvaluator(profile="full")
        assert p.is_tool_allowed("anything") is True


class TestCheckExecWorkspace:
    """Containment applies to arguments that name a location, and only when a root is configured."""

    async def test_path_outside_workspace_rejected(self, tmp_path: Path):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL, workspace_root=str(tmp_path))
        allowed, reason = await p.check_exec("t", {"path": str(tmp_path.parent / "escape")})
        assert allowed is False
        assert "outside the workspace root" in (reason or "")

    async def test_path_inside_workspace_passes(self, tmp_path: Path):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL, workspace_root=str(tmp_path))
        allowed, _reason = await p.check_exec("t", {"path": str(tmp_path / "ok.txt")})
        assert allowed is True

    async def test_suffixed_location_key_is_scanned(self, tmp_path: Path):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL, workspace_root=str(tmp_path))
        allowed, _reason = await p.check_exec("t", {"output_file": str(tmp_path.parent / "escape")})
        assert allowed is False

    async def test_command_text_is_not_mistaken_for_a_path(self, tmp_path: Path):
        # a shell command is not a filesystem location; resolving it as one both denies harmless
        # calls and approves escapes, so restraint here belongs to EXEC_SECURITY instead
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL, workspace_root=str(tmp_path))
        allowed, _reason = await p.check_exec("shell_execute", {"command": "type C:\\Windows\\System32\\config\\SAM"})
        assert allowed is True

    async def test_empty_location_argument_is_not_a_denial(self, tmp_path: Path):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL, workspace_root=str(tmp_path))
        allowed, _reason = await p.check_exec("shell_execute", {"command": "ls", "cwd": ""})
        assert allowed is True

    async def test_no_root_configured_skips_containment(self):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.FULL, workspace_only=True, workspace_root=None)
        allowed, _reason = await p.check_exec("t", {"path": "C:\\Windows\\System32\\config\\SAM"})
        assert allowed is True

    async def test_workspace_only_off_skips_containment(self, tmp_path: Path):
        p = ToolPolicyEvaluator(
            exec_security=ExecSecurity.FULL, workspace_only=False, workspace_root=str(tmp_path)
        )
        allowed, _reason = await p.check_exec("t", {"path": str(tmp_path.parent / "escape")})
        assert allowed is True


class TestCheckExecAskModes:
    async def test_ask_off_allows(self):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK, exec_ask=ExecAskMode.OFF)
        allowed, _ = await p.check_exec("t")
        assert allowed is True

    async def test_ask_always_confirmed(self):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK)
        confirm = AsyncMock(return_value=True)
        allowed, _ = await p.check_exec("t", confirm_fn=confirm)
        assert allowed is True
        confirm.assert_awaited_once()

    async def test_ask_always_declined(self):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK)
        confirm = AsyncMock(return_value=False)
        allowed, reason = await p.check_exec("t", confirm_fn=confirm)
        assert allowed is False
        assert "cancelled" in (reason or "")

    async def test_ask_always_without_confirm_fn_denies(self):
        # "ask" without anybody to ask is not "ask"; running anyway turns the mode into a comment
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK)
        allowed, reason = await p.check_exec("t")
        assert allowed is False
        assert "confirmer" in (reason or "")

    async def test_ask_on_miss_confirms_unlisted(self):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK, exec_ask=ExecAskMode.ON_MISS)
        confirm = AsyncMock(return_value=True)
        allowed, _ = await p.check_exec("unlisted_tool", confirm_fn=confirm)
        assert allowed is True
        confirm.assert_awaited_once()

    async def test_ask_on_miss_declined(self):
        p = ToolPolicyEvaluator(exec_security=ExecSecurity.ASK, exec_ask=ExecAskMode.ON_MISS)
        confirm = AsyncMock(return_value=False)
        allowed, reason = await p.check_exec("unlisted_tool", confirm_fn=confirm)
        assert allowed is False
        assert "cancelled" in (reason or "")

    async def test_ask_on_miss_skips_confirm_for_allowed_tool(self):
        p = ToolPolicyEvaluator(
            profile="full", allow=["known"], exec_security=ExecSecurity.ASK, exec_ask=ExecAskMode.ON_MISS
        )
        confirm = AsyncMock(return_value=False)
        allowed, _ = await p.check_exec("known", confirm_fn=confirm)
        assert allowed is True
        confirm.assert_not_awaited()

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

ALLOWED_PROFILES = frozenset({"messaging", "minimal", "full"})

MAX_PATH_DEPTH = 20


class ExecSecurity(StrEnum):
    DENY = "deny"
    ASK = "ask"
    FULL = "full"


class ExecAskMode(StrEnum):
    OFF = "off"
    ON_MISS = "on-miss"
    ALWAYS = "always"


def _resolve_safe(path_str: str, root: Path | None = None) -> Path | None:
    if not path_str or not path_str.strip():
        return None
    if "\x00" in path_str:
        return None
    try:
        p = Path(path_str).resolve(strict=False)
    except (RuntimeError, OSError):
        return None
    parts = p.parts
    depth = sum(1 for part in parts if part not in ("/", "\\", "."))
    if depth > MAX_PATH_DEPTH:
        return None
    if root is not None:
        root_resolved = root.resolve()
        try:
            p.relative_to(root_resolved)
        except ValueError:
            return None
    return p


class ToolPolicyEvaluator:
    def __init__(
        self,
        profile: str = "messaging",
        deny: list[str] | None = None,
        allow: list[str] | None = None,
        exec_security: ExecSecurity = ExecSecurity.DENY,
        exec_ask: ExecAskMode = ExecAskMode.ALWAYS,
        workspace_only: bool = True,
        workspace_root: str | None = None,
    ):
        self.profile = profile if profile in ALLOWED_PROFILES else "messaging"
        self._deny = set(deny or [])
        self._allow = set(allow or [])
        self.exec_security = exec_security
        self.exec_ask = exec_ask
        self.workspace_only = workspace_only
        self._workspace_root = _resolve_safe(workspace_root) if workspace_root else None

        self._profiles: dict[str, set[str]] = {
            "messaging": {"file.read", "notify.send", "memory.search", "web.search"},
            "minimal": {"notify.send"},
            "full": set(),
        }

    def set_workspace_root(self, path: str | Path):
        root = _resolve_safe(str(path)) if isinstance(path, Path) else _resolve_safe(path)
        if root is None:
            raise ValueError(f"Invalid workspace root: {path}")
        self._workspace_root = root

    def _profile_tools(self) -> set[str]:
        return self._profiles.get(self.profile, set())

    def is_tool_allowed(self, tool_name: str) -> bool:
        try:
            from raven.core.security.policy_engine import policy_engine

            rs = policy_engine.get_ruleset("tools")
            if rs is not None and len(rs.rules) > 0 and not policy_engine.check("tools", {"tool": tool_name, "profile": self.profile, "action": "call"}):
                return False
        except ImportError:
            pass

        if tool_name in self._deny:
            return False
        if self._allow:
            return tool_name in self._allow
        profile_set = self._profile_tools()
        if profile_set:
            return tool_name in profile_set
        return True

    def check_path(self, path: str) -> bool:
        if not self.workspace_only or not self._workspace_root:
            return True
        resolved = _resolve_safe(path, self._workspace_root)
        if resolved is None:
            return False
        try:
            resolved.relative_to(self._workspace_root)
            return True
        except ValueError:
            return False

    async def check_exec(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        confirm_fn: Any = None,
    ) -> tuple[bool, str | None]:
        args = args or {}

        try:
            from raven.core.security.policy_engine import policy_engine

            allowed = policy_engine.check(
                "exec", {"tool": tool_name, "args": args, "exec_security": self.exec_security.value}
            )
            if not allowed:
                return False, "exec denied by policy engine"
        except ImportError:
            pass

        if self.exec_security == ExecSecurity.DENY:
            return False, "exec denied by policy (security=deny)"

        if self.workspace_only:
            for _k, v in args.items():
                if isinstance(v, str):
                    resolved = _resolve_safe(v, self._workspace_root)
                    if resolved is None:
                        return False, f"path '{v}' outside workspace root or invalid"

        if self.exec_security == ExecSecurity.FULL:
            return True, None

        if self.exec_security == ExecSecurity.ASK:
            if self.exec_ask == ExecAskMode.OFF:
                return True, None
            if self.exec_ask == ExecAskMode.ALWAYS:
                if confirm_fn:
                    confirmed = await confirm_fn(tool_name, args)
                    if not confirmed:
                        return False, "exec cancelled by user"
                return True, None
            if self.exec_ask == ExecAskMode.ON_MISS:
                if tool_name not in self._allow and tool_name not in self._profile_tools() and confirm_fn:
                    confirmed = await confirm_fn(tool_name, args)
                    if not confirmed:
                        return False, "exec cancelled by user"
                return True, None

        return True, None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "deny": list(self._deny),
            "allow": list(self._allow),
            "exec_security": self.exec_security.value,
            "exec_ask": self.exec_ask.value,
            "workspace_only": self.workspace_only,
            "workspace_root": str(self._workspace_root) if self._workspace_root else None,
        }

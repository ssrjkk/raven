from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger

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


# Tools that run something outside the assistant's own text: command execution, network egress,
# repository mutation, sub-processes. EXEC_SECURITY and EXEC_ASK are about these, and the task
# registry strips exactly this set so a planner-authored step cannot escalate to a shell.
EXEC_CLASS_TOKENS: tuple[str, ...] = (
    "shell",
    "python",
    "process_",
    "browser_",
    "mcp_",
    "node_",
    "chaos_",
    "db_query",
    "email_send",
    "http_post",
    "git_commit",
    "git_push",
    "git_pull",
    "git_checkout",
    "git_create_pr",
    "git_review",
    "plugin_",
)


def is_exec_class(tool_name: str) -> bool:
    return any(token in tool_name for token in EXEC_CLASS_TOKENS)


# Argument keys that carry a filesystem location. Containment is only meaningful for these: a
# "command", "url" or "sql" string is not a path, and restraining those is EXEC_SECURITY's job,
# not a Path.resolve() of prose that happens to contain separators. Matching is by exact key or by
# a location suffix, so "output_format" is not mistaken for "output_file".
PATH_ARG_KEYS: frozenset[str] = frozenset(
    {"path", "file", "filename", "filepath", "dir", "directory", "folder", "cwd", "root", "source", "target"}
)
PATH_ARG_SUFFIXES: tuple[str, ...] = ("_path", "_file", "_filepath", "_dir", "_directory", "_root", "_cwd")


def is_location_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in PATH_ARG_KEYS or any(lowered.endswith(suffix) for suffix in PATH_ARG_SUFFIXES)


def path_args(args: dict[str, Any]) -> list[tuple[str, str]]:
    """Non-empty string arguments whose key names a location."""
    return [(key, value) for key, value in args.items() if isinstance(value, str) and value.strip() and is_location_key(key)]


def resolve_within_root(path_str: str, root: Path | None = None) -> Path | None:
    """The resolved path when it is usable and inside root; None for anything unsafe."""
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
        self._workspace_root = resolve_within_root(workspace_root) if workspace_root else None

        self._profiles: dict[str, set[str]] = {
            "messaging": {"files.read", "api.http_get", "memory.recall", "browser.search"},
            "minimal": {"api.http_get"},
            "full": set(),
        }

    def set_workspace_root(self, path: str | Path):
        root = resolve_within_root(str(path)) if isinstance(path, Path) else resolve_within_root(path)
        if root is None:
            msg = f"Invalid workspace root: {path}"
            raise ValueError(msg)
        self._workspace_root = root

    def _profile_tools(self) -> set[str]:
        return self._profiles.get(self.profile, set())

    def is_tool_allowed(self, tool_name: str) -> bool:
        try:
            from raven.core.security.policy_engine import policy_engine

            rs = policy_engine.get_ruleset("tools")
            if rs is not None and len(rs.rules) > 0:
                effect, _ = policy_engine.evaluate("tools", {"tool": tool_name, "profile": self.profile, "action": "call"})
                if effect == "deny":
                    return False
        except ImportError as e:
            logger.debug("policy_engine not available: {}", e)

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
        resolved = resolve_within_root(path, self._workspace_root)
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

            rs = policy_engine.get_ruleset("exec")
            if rs is not None and len(rs.rules) > 0 and not policy_engine.check(
                "exec",
                {"tool": tool_name, "args": args, "exec_security": self.exec_security.value},
            ):
                return False, "exec denied by policy engine"
        except ImportError as e:
            logger.debug("policy_engine not available: {}", e)

        if self.exec_security == ExecSecurity.DENY:
            return False, "exec denied by policy (security=deny)"

        if self.workspace_only and self._workspace_root is not None:
            for key, value in path_args(args):
                if resolve_within_root(value, self._workspace_root) is None:
                    return False, f"argument '{key}'='{value}' is outside the workspace root"

        if self.exec_security == ExecSecurity.FULL:
            return True, None

        if self.exec_security == ExecSecurity.ASK:
            if self.exec_ask == ExecAskMode.OFF:
                return True, None
            needs_confirmation = self.exec_ask == ExecAskMode.ALWAYS or (
                self.exec_ask == ExecAskMode.ON_MISS
                and tool_name not in self._allow
                and tool_name not in self._profile_tools()
            )
            if not needs_confirmation:
                return True, None
            if confirm_fn is None:
                # asking is the point of this mode; running anyway is how a control becomes a comment
                return False, (
                    f"{tool_name} requires confirmation and no confirmer is wired to this caller "
                    "(EXEC_ASK=always with nobody to ask; pass a confirm_fn or set EXEC_ASK=off deliberately)"
                )
            if not await confirm_fn(tool_name, args):
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

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.workspace import allowed_roots

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
    "_exec",
    "trigger",
    "ci_run_workflow",
    "ci_jenkins_job",
    "run_code",
    "http_put",
    "http_delete",
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
    # Plugin tools arrive namespaced (`process.run`), registry tools bare (`process_kill`). Matching
    # the raw string meant the same capability was gated under one name and free under the other, so
    # EXEC_SECURITY could be walked past by calling the dotted twin. Separators are equal here.
    normalized = tool_name.replace(".", "_")
    return any(token in normalized for token in EXEC_CLASS_TOKENS)


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

    def _ruleset_denial(self, input_data: dict[str, Any]) -> str | None:
        """Why the shipped ruleset refuses this call, or None when it does not.

        Only a ``deny`` effect is acted on: a file can tighten what the operator configured, never
        widen it, so an ``allow`` effect falls through to the layers below. An unreadable ruleset
        refuses too — a policy that cannot be read is not a policy that permits everything.
        """
        try:
            from raven.core.security.policy_engine import PolicyLoadError, policy_engine
        except ImportError as exc:
            logger.debug("policy_engine not available: {}", exc)
            return None

        try:
            effect, rule_name = policy_engine.evaluate("tools", input_data)
        except PolicyLoadError as exc:
            logger.error("Tool policy ruleset unreadable, refusing: {}", exc)
            return f"policy ruleset unreadable ({exc})"

        if effect == "deny":
            return f"denied by policy rule '{rule_name}'"
        return None

    def denial_reason(self, tool_name: str) -> str | None:
        """Which layer refuses this call, in the words an operator can act on. None means it may run.

        Callers used to say `TOOLS_DENY` for every refusal this method returns, which became wrong
        the moment the ruleset gained a voice: a tool named only in `policy/tools.json` was reported
        as if the `TOOLS_DENY` switch had named it.
        """
        if tool_name in self._deny:
            return f"'{tool_name}' is in TOOLS_DENY"

        ruleset = self._ruleset_denial({"tool": tool_name, "profile": self.profile, "action": "call"})
        if ruleset is not None:
            return f"denied by the policy ruleset ({ruleset})"

        if self._allow:
            if tool_name not in self._allow:
                return f"'{tool_name}' is not in TOOLS_ALLOW"
            return None
        profile_set = self._profile_tools()
        if profile_set and tool_name not in profile_set:
            return f"'{tool_name}' is not offered to the '{self.profile}' profile"
        return None

    def is_tool_allowed(self, tool_name: str) -> bool:
        return self.denial_reason(tool_name) is None

    def check_path(self, path: str) -> bool:
        if not self.workspace_only:
            return True
        return self._confined(path)

    def _roots(self) -> tuple[Path, ...]:
        """The directories a path argument may resolve into — the pinned root, or the one the deployment resolves."""
        return (self._workspace_root,) if self._workspace_root is not None else allowed_roots()

    def _confined(self, path_str: str) -> bool:
        return any(resolve_within_root(path_str, root) is not None for root in self._roots())

    async def check_exec(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        confirm_fn: Any = None,
    ) -> tuple[bool, str | None]:
        args = args or {}

        if self.exec_security == ExecSecurity.DENY:
            return False, "exec denied by policy (security=deny)"

        # After the operator's own switch, before anything that could run or ask: a tool the
        # ruleset names must not reach the prompt, and a refusal that says `security=deny` when
        # the file is the one refusing would send the operator to the wrong switch.
        denial = self._ruleset_denial(
            {
                "tool": tool_name,
                "args": args,
                "profile": self.profile,
                "action": "exec",
                "exec_security": self.exec_security.value,
            }
        )
        if denial is not None:
            return False, f"exec refused by policy engine ({denial})"

        if self.workspace_only:
            for key, value in path_args(args):
                if not self._confined(value):
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


def policy_from_settings(profile: str | None = None, workspace_only: bool | None = None) -> ToolPolicyEvaluator:
    """Build the operator's tool policy the one way, so no surface invents its own defaults."""
    from raven.core.config import _DEFAULT_TOOLS_DENY, settings

    deny_raw = settings.tools_deny
    deny_list = [d.strip() for d in deny_raw.split(",") if d.strip()] if deny_raw else list(_DEFAULT_TOOLS_DENY)
    allow_raw = settings.tools_allow
    allow_list = [a.strip() for a in allow_raw.split(",") if a.strip()] if allow_raw else []
    return ToolPolicyEvaluator(
        profile=profile or settings.tools_profile,
        deny=deny_list,
        allow=allow_list,
        exec_security=ExecSecurity(settings.exec_security),
        exec_ask=ExecAskMode(settings.exec_ask_mode),
        workspace_only=settings.workspace_only if workspace_only is None else workspace_only,
        # No root is pinned here on purpose: `settings.resolved_workspace` was a second source of
        # truth that ignored `--workspace` and `RAVEN_WORKSPACE`, so the gate and the tool could
        # answer differently for one path. `_roots()` resolves the one root instead.
        workspace_root=None,
    )


async def mcp_deny_reason(tool_name: str, arguments: dict[str, Any] | None) -> str:
    """Why the MCP surface has to refuse this call; empty means it may proceed.

    The profile allow-list is the messaging agent's trust boundary, not a server's - an MCP
    client is the operator's own tool surface - so profile filtering is lifted here, and so is
    path containment: these tools are already confined by `ravencode/runtime/workspace.py:confine`
    against the same root this policy resolves (`raven/core/workspace.py`), so checking it here as
    well would only add a second way to refuse the same path.
    """
    policy = policy_from_settings(profile="full", workspace_only=False)
    reason = policy.denial_reason(tool_name)
    if reason is not None:
        return f"'{tool_name}' is denied by policy - {reason}"
    if is_exec_class(tool_name):
        allowed, reason = await policy.check_exec(tool_name, arguments or {}, confirm_fn=None)
        if not allowed:
            return f"'{tool_name}' is denied by policy - {reason}"
    return ""

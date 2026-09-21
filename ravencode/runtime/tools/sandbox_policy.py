from __future__ import annotations

import contextvars
from typing import Any

_current_sandbox_policy: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ravencode_sandbox_policy", default="main"
)



_SANDBOX_SOFT_MUTATORS: frozenset[str] = frozenset(
    {
        "write",
        "edit",
        "smart_edit",
        "patch",
        "bash",
        "sandbox_exec",
        "git_add",
        "git_commit",
        "auto_commit",
        "undo",
        "redo",
        "checkpoint_restore",
        "undo_changes",
    }
)



_CODE_EXEC_TOOLS: frozenset[str] = frozenset(
    {
        "read",
        "glob",
        "grep",
        "read_image",
        "write",
        "edit",
        "smart_edit",
        "patch",
        "verify",
        "format_file",
        "format_files",
        "bash",
        "sandbox_exec",
        "git_status",
        "git_diff",
        "git_log",
        "git_add",
        "git_commit",
        "auto_commit",
        "todo_write",
        "todo_list",
        "todo_update",
        "todo_clear",
        "lsp_completion",
        "lsp_definition",
        "lsp_references",
        "lsp_hover",
        "think",
        "create_artifact",
        "undo",
        "redo",
        "checkpoint_save",
        "checkpoint_restore",
        "checkpoint_list",
        "undo_changes",
        "skill",
        "download_skill",
        "set_skill_registry",
        "anchored_summary_read",
        "anchored_summary_write",
        "anchored_summary_append",
        "anchored_summary_clear",
        "sandbox_policy",
    }
)



_WEB_BROWSING_TOOLS: frozenset[str] = frozenset(
    {
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_screenshot",
        "browser_get_html",
        "browser_evaluate",
        "browser_close",
        "web_search",
        "web_fetch",
        "read",
        "glob",
        "grep",
        "think",
        "question",
        "sandbox_policy",
    }
)



_SANDBOX_POLICY_RULES: dict[str, dict[str, Any]] = {
    "main": {"allow": None, "deny_prefix": frozenset(), "deny_exact": frozenset()},
    "non-main": {
        "allow": None,
        "deny_prefix": frozenset({"browser_", "cron_", "nodes_"}),
        "deny_exact": frozenset({"canvas_render", "talk"}),
    },
    "code-exec": {"allow": _CODE_EXEC_TOOLS, "deny_prefix": frozenset(), "deny_exact": frozenset()},
    "web-browsing": {"allow": _WEB_BROWSING_TOOLS, "deny_prefix": frozenset(), "deny_exact": frozenset()},
    "read-only": {"allow": None, "deny_prefix": frozenset(), "deny_exact": _SANDBOX_SOFT_MUTATORS},
}




def _sandbox_deny_reason(name: str) -> str:
    policy = _current_sandbox_policy.get()
    rules = _SANDBOX_POLICY_RULES.get(policy)
    if not rules:
        return ""
    allow = rules.get("allow")
    if allow is not None and name not in allow:
        return f"Tool '{name}' not allowed in {policy} sandbox policy"
    if name in rules.get("deny_exact", frozenset()) or any(
        name.startswith(prefix) for prefix in rules.get("deny_prefix", frozenset())
    ):
        return f"Tool '{name}' denied in {policy} sandbox policy"
    return ""




async def _sandbox_policy_handler(policy: str | None = None) -> str:
    if policy:
        valid = {"main", "non-main", "code-exec", "web-browsing", "read-only"}
        if policy not in valid:
            return f"[error] unknown policy: {policy}. Available: {', '.join(sorted(valid))}"
        _current_sandbox_policy.set(policy)
        return f"Sandbox policy set to: {policy}"
    return f"Current sandbox policy: {_current_sandbox_policy.get()}"

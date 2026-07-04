from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SandboxPolicy:
    name: str
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None
    allow_network: bool = False
    allow_read: list[str] | None = None
    allow_write: list[str] | None = None
    max_memory_mb: int = 256
    max_cpu_percent: int = 50
    max_pids: int = 64
    timeout_seconds: int = 30
    docker_image: str = "python:3.12-slim"
    sandbox_mode: str = "docker"
    network_rules: dict[str, Any] | None = None


MAIN_SESSION_POLICY = SandboxPolicy(
    name="main",
    allowed_tools=None,
    denied_tools=[],
    allow_network=True,
    max_memory_mb=512,
    timeout_seconds=60,
    sandbox_mode="none",
)

NON_MAIN_SESSION_POLICY = SandboxPolicy(
    name="non-main",
    allowed_tools=["bash", "process", "read", "write", "edit", "glob", "grep", "sessions_list", "sessions_history"],
    denied_tools=["browser_open", "browser_screenshot", "canvas_render", "canvas_show",
                  "nodes_register", "nodes_exec", "cron_schedule", "gateway"],
    allow_network=False,
    max_memory_mb=128,
    timeout_seconds=15,
    sandbox_mode="docker",
)

CODE_EXECUTION_POLICY = SandboxPolicy(
    name="code-exec",
    allowed_tools=["read", "write", "bash", "process"],
    denied_tools=["browser_open", "browser_screenshot", "web_search", "web_fetch",
                  "network", "nodes", "cron", "gateway", "canvas"],
    allow_network=True,
    max_memory_mb=256,
    max_cpu_percent=50,
    timeout_seconds=30,
    sandbox_mode="docker",
    network_rules={"allow": ["pypi.org", "github.com", "files.pythonhosted.org"], "deny": ["*"]},
)

WEB_BROWSING_POLICY = SandboxPolicy(
    name="web-browsing",
    allowed_tools=["browser_open", "browser_screenshot", "web_fetch", "web_search"],
    denied_tools=["bash", "write", "edit", "nodes", "cron", "gateway"],
    allow_network=True,
    max_memory_mb=512,
    timeout_seconds=60,
    sandbox_mode="none",
)

READ_ONLY_POLICY = SandboxPolicy(
    name="read-only",
    allowed_tools=["read", "glob", "grep", "web_search", "web_fetch"],
    denied_tools=["write", "edit", "bash", "browser_open", "browser_screenshot"],
    allow_network=True,
    max_memory_mb=256,
    timeout_seconds=30,
    sandbox_mode="none",
)


POLICY_REGISTRY: dict[str, SandboxPolicy] = {
    "main": MAIN_SESSION_POLICY,
    "non-main": NON_MAIN_SESSION_POLICY,
    "code-exec": CODE_EXECUTION_POLICY,
    "web-browsing": WEB_BROWSING_POLICY,
    "read-only": READ_ONLY_POLICY,
}


def get_policy(name: str) -> SandboxPolicy:
    return POLICY_REGISTRY.get(name, NON_MAIN_SESSION_POLICY)


def check_tool_allowed(policy: SandboxPolicy, tool_name: str) -> tuple[bool, str]:
    if policy.allowed_tools and tool_name not in policy.allowed_tools:
        return False, f"Tool '{tool_name}' not allowed in {policy.name} sandbox"
    if policy.denied_tools and tool_name in policy.denied_tools:
        return False, f"Tool '{tool_name}' denied in {policy.name} sandbox"
    return True, ""


def check_path_allowed(policy: SandboxPolicy, path: str, mode: str = "read") -> tuple[bool, str]:
    allow_list = policy.allow_read if mode == "read" else policy.allow_write
    if allow_list is not None:
        allowed = any(path.startswith(a) for a in allow_list)
        if not allowed:
            return False, f"Path '{path}' not allowed for {mode} in {policy.name} sandbox"
    return True, ""


def session_type_to_policy(session_type: str) -> SandboxPolicy:
    if session_type == "main":
        return MAIN_SESSION_POLICY
    if session_type == "code":
        return CODE_EXECUTION_POLICY
    if session_type == "web":
        return WEB_BROWSING_POLICY
    if session_type == "plan":
        return READ_ONLY_POLICY
    return NON_MAIN_SESSION_POLICY

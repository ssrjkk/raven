"""Security layer.

Names here resolve to their submodule on first use rather than at import. `code_sandbox` is the pure
AST contract, imported by the sandboxed child process, and an eager package init made every child
load gateway settings, loguru and asyncio just to reach it -- which cost each sandboxed run a config
startup line (`Loaded WEB_SECRET_KEY from <path>`) inside the tool output it returns to a model.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ContextVisibility": "raven.core.security.context_filter",
    "PIIDetection": "raven.core.security.context_filter",
    "PIIEngine": "raven.core.security.context_filter",
    "analyze_pii": "raven.core.security.context_filter",
    "mask_pii": "raven.core.security.context_filter",
    "redact_pii": "raven.core.security.context_filter",
    "sanitize_external_content": "raven.core.security.context_filter",
    "PolicyEngine": "raven.core.security.policy_engine",
    "Rule": "raven.core.security.policy_engine",
    "RuleSet": "raven.core.security.policy_engine",
    "policy_engine": "raven.core.security.policy_engine",
    "SecurityAudit": "raven.core.security.security_audit",
    "ExecAskMode": "raven.core.security.tool_policy",
    "ExecSecurity": "raven.core.security.tool_policy",
    "ToolPolicyEvaluator": "raven.core.security.tool_policy",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    source = _EXPORTS.get(name)
    if source is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(source), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)

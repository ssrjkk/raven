"""
ravencode — Autonomous AI engineering framework.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ravencode.api.client import AIOSClient
    from ravencode.agents.orchestrator import Orchestrator
    from ravencode.runtime.shell import ShellExecutor


def __getattr__(name: str):
    _lazy_map = {
        "AIOSClient": "ravencode.api.client",
        "Orchestrator": "ravencode.agents.orchestrator",
        "ShellExecutor": "ravencode.runtime.shell",
    }
    module_path = _lazy_map.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(module_path)
    attr = getattr(mod, name)
    globals()[name] = attr
    return attr


__all__ = [
    "AIOSClient",
    "Orchestrator",
    "ShellExecutor",
]

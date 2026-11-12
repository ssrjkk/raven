"""Every ``TOOLS_DENY`` entry must name a tool some surface actually serves.

`ToolPolicyEvaluator.denial_reason` matches by exact string, and the shipped list deliberately
mixes two spellings for the same capability: registry tools are bare (`process_kill`) and plugin
tools arrive namespaced (`process.kill`). A rename on either side therefore turns the switch into
a comment without failing anything, which is how a denied-by-default control goes silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from raven.core.config import _DEFAULT_TOOLS_DENY
from raven.core.plugin_loader import PluginLoader
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.register_all import register_all_tools

_BUNDLED_PLUGINS = Path(__file__).resolve().parents[2] / "raven" / "plugins"


@pytest.fixture(scope="module")
def served_tool_names() -> set[str]:
    registry = ToolRegistry()
    register_all_tools(registry)
    names = {spec.name for spec in registry.list()}
    loader = PluginLoader()
    for plugin_dir in sorted(p for p in _BUNDLED_PLUGINS.iterdir() if (p / "plugin.py").exists()):
        names |= {tool.name for tool in loader.load_from_dir(plugin_dir)}
    return names


def test_both_tool_naming_schemes_are_collected(served_tool_names: set[str]) -> None:
    """A resolver that silently finds no plugins would make the deny check below vacuous."""
    namespaced = {n for n in served_tool_names if "." in n}
    assert len(served_tool_names) > 200
    assert {"process.kill", "git.git_push", "sessions.sessions_spawn"} <= namespaced


def test_every_default_deny_entry_names_a_served_tool(served_tool_names: set[str]) -> None:
    inert = sorted(name for name in _DEFAULT_TOOLS_DENY if name not in served_tool_names)
    assert not inert, f"TOOLS_DENY entries no surface serves, so nothing is denied: {inert}"


def test_the_settings_built_policy_denies_every_default_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default list reaches the evaluator as one comma-joined string. A parser change (another
    separator, an unstripped space) un-denies tools without failing any other check."""
    from raven.core.config import settings
    from raven.core.security.tool_policy import policy_from_settings

    monkeypatch.setattr(settings, "tools_deny", ",".join(_DEFAULT_TOOLS_DENY))
    policy = policy_from_settings(profile="full")
    still_offered = [name for name in _DEFAULT_TOOLS_DENY if policy.denial_reason(name) != f"'{name}' is in TOOLS_DENY"]
    assert not still_offered, f"not denied by the policy built from settings: {still_offered}"

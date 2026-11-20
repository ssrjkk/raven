"""The credential rule, checked at every resolver that confines a tool path.

Five places decide whether a path a tool named may be opened: `raven/core/workspace.py` (the plugin
tools and the aios bridge), `ravencode/runtime/workspace.py` (the coding agent and the MCP surface),
`raven/core/security/path_guard.py` (the registry file tools, the debugger, git), the tool policy's
containment, and `raven/tools/tests.py` (the test generator, which opens the source it is handed and
puts it in a prompt). A rule only some of them know is a rule an injected message walks past by
asking the twin tool, so this file drives all five against the same names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from raven.core.security.path_guard import confine_path
from raven.core.security.secret_paths import credential_reason
from raven.core.security.tool_policy import ToolPolicyEvaluator
from raven.core.workspace import confine as tool_confine
from raven.tools.tests import _confine as confine_tests_tool_path
from ravencode.runtime.workspace import confine as agent_confine
from ravencode.runtime.workspace import reset_workspace_root, set_workspace_root

CREDENTIALS = (
    ".env",
    ".env.production",
    "secrets/id_rsa",
    "deploy/api.key",
    "certs/server.pem",
    ".ssh/authorized_keys",
    ".git-credentials",
    "data/web_secret_key",
    "netrc",
)

# The files a repository ships beside the real ones: placeholders, public halves, documentation.
TEMPLATES = (".env.example", ".env.sample", "deploy/api.key.template", "secrets/id_rsa.pub", "docs/env.md")


@pytest.fixture
def ws(tmp_path: Path):
    root = tmp_path / "ws"
    (root / "secrets").mkdir(parents=True)
    (root / "notes.md").write_text("hello", encoding="utf-8")
    token = set_workspace_root(root)
    try:
        yield root
    finally:
        reset_workspace_root(token)


@pytest.mark.parametrize("name", CREDENTIALS)
def test_a_credential_name_is_recognised(name: str) -> None:
    assert credential_reason(Path("/srv/app") / name, Path("/srv/app")) is not None


@pytest.mark.parametrize("name", TEMPLATES)
def test_a_template_or_public_half_is_not_a_credential(name: str) -> None:
    assert credential_reason(Path("/srv/app") / name, Path("/srv/app")) is None


@pytest.mark.parametrize("name", CREDENTIALS)
def test_the_plugin_tool_resolver_refuses_a_credential(ws: Path, name: str) -> None:
    with pytest.raises(PermissionError, match="credential"):
        tool_confine(name)


@pytest.mark.parametrize("name", CREDENTIALS)
def test_the_coding_agent_resolver_refuses_a_credential(ws: Path, name: str) -> None:
    with pytest.raises(PermissionError, match="credential"):
        agent_confine(name)


@pytest.mark.parametrize("name", CREDENTIALS)
def test_the_registry_resolver_refuses_a_credential(ws: Path, name: str) -> None:
    with pytest.raises(PermissionError, match="credential"):
        confine_path(str(ws / name), ws)


@pytest.mark.parametrize("name", CREDENTIALS)
def test_the_tool_policy_refuses_a_credential_argument(ws: Path, name: str) -> None:
    policy = ToolPolicyEvaluator(profile="full", workspace_only=True, workspace_root=str(ws))
    assert policy.check_path(str(ws / name)) is False
    assert "credential" in str(policy.path_denial_reason(str(ws / name)))


@pytest.mark.parametrize("name", CREDENTIALS)
def test_the_test_generator_resolver_refuses_a_credential(ws: Path, name: str) -> None:
    with pytest.raises(PermissionError, match="credential"):
        confine_tests_tool_path(str(ws / name))


def test_the_test_generator_keeps_ordinary_sources(ws: Path) -> None:
    assert confine_tests_tool_path(str(ws / "notes.md")).name == "notes.md"
    assert confine_tests_tool_path(str(ws / ".env.example")).name == ".env.example"


def test_the_rule_bends_for_ordinary_files(ws: Path) -> None:
    assert tool_confine("notes.md").name == "notes.md"
    assert agent_confine("notes.md").name == "notes.md"
    assert confine_path(str(ws / "notes.md"), ws).name == "notes.md"
    for name in TEMPLATES:
        assert tool_confine(name) is not None


def test_a_checkout_under_a_credential_named_directory_still_works(tmp_path: Path) -> None:
    """The name of where the workspace sits is the operator's choice; the names inside it are the rule."""
    root = tmp_path / ".aws" / "proj"
    root.mkdir(parents=True)
    (root / "settings.py").write_text("X = 1", encoding="utf-8")
    token = set_workspace_root(root)
    try:
        assert agent_confine("settings.py").name == "settings.py"
        assert tool_confine("settings.py").name == "settings.py"
    finally:
        reset_workspace_root(token)


def test_a_path_outside_the_roots_keeps_its_own_refusal(ws: Path) -> None:
    """The credential wording is only for a name the boundary already admitted: sending an operator to
    the workspace ruleset to explain a path that is nowhere near it would be a wrong diagnosis."""
    outside = Path(ws.anchor) / "raven-boundary-probe" / "plain.txt"
    with pytest.raises(PermissionError, match="outside"):
        tool_confine(str(outside))
    with pytest.raises(PermissionError, match="outside"):
        agent_confine(str(outside))

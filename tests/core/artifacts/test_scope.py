from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from raven.core.artifacts.model import ArtifactContext, ArtifactScope
from raven.core.artifacts.scope import ScopeMatcher


def _ctx(**kwargs: Any) -> ArtifactContext:
    return ArtifactContext(**kwargs)


def test_empty_scope_matches_everything() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope()
    assert matcher.match(scope, _ctx(agent_id="coder", channel="telegram"))


def test_agent_filter() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(agents=["coder"])
    assert matcher.match(scope, _ctx(agent_id="coder"))
    assert not matcher.match(scope, _ctx(agent_id="assistant"))


def test_role_and_channel_filter() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(roles=["architect"], channels=["webchat"])
    assert matcher.match(scope, _ctx(role="architect", channel="webchat"))
    assert not matcher.match(scope, _ctx(role="architect", channel="telegram"))
    assert not matcher.match(scope, _ctx(role="coder", channel="webchat"))


def test_command_filter() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(commands=["shipit"])
    assert matcher.match(scope, _ctx(command="shipit"))
    assert not matcher.match(scope, _ctx(command="build"))


def test_task_type_filter() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(task_types=["refactor"])
    assert matcher.match(scope, _ctx(task_type="refactor"))
    assert not matcher.match(scope, _ctx(task_type="test"))


def test_path_glob_filter() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(paths=["services/*", "tests/**"])
    root = Path("/repo")
    assert matcher.match(scope, _ctx(cwd=root / "services" / "auth", root=root))
    assert matcher.match(scope, _ctx(cwd=root / "tests" / "unit" / "test_x.py", root=root))
    assert not matcher.match(scope, _ctx(cwd=root / "web" / "App.tsx", root=root))


def test_enabled_false_never_matches() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(enabled=False)
    assert not matcher.match(scope, _ctx(agent_id="coder"))


def test_when_keyword_matches_task_text() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(when="deploy, release")
    assert matcher.match(scope, _ctx(text="please deploy the api now"))
    assert matcher.match(scope, _ctx(text="prepare a release"))
    assert not matcher.match(scope, _ctx(text="fix the login bug"))


def test_when_requires_text() -> None:
    matcher = ScopeMatcher()
    scope = ArtifactScope(when="deploy")
    assert not matcher.match(scope, _ctx(text=""))


def test_scope_from_dict_strings_and_lists() -> None:
    scope = ArtifactScope.from_dict({"agents": "coder", "task_types": ["test", "refactor"], "enabled": False})
    assert scope.agents == ["coder"]
    assert scope.task_types == ["test", "refactor"]
    assert scope.enabled is False


def test_scope_from_dict_bad_types_ignored() -> None:
    scope = ArtifactScope.from_dict({"agents": None, "roles": 42, "enabled": "yes"})
    assert scope.agents == []
    assert scope.roles == []
    assert scope.enabled is True


@pytest.mark.parametrize(
    ("pattern", "rel", "name", "expected"),
    [
        ("*.py", "src/app.py", "app.py", True),
        ("src/*", "src/app.py", "app.py", True),
        ("tests/**", "tests/unit/test_x.py", "test_x.py", True),
        ("docs", "docs", "docs", True),
    ],
)
def test_path_matches(pattern: str, rel: str, name: str, expected: bool) -> None:
    from raven.core.artifacts.model import path_matches

    assert path_matches([pattern], rel, name) is expected

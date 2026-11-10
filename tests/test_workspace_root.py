"""One workspace root for every surface that confines a path.

The defect this gates was the opposite shape: `WORKSPACE_ONLY=true` confined nothing at the policy
layer — `check_path()` answered True for a system binary — while the plugin tools refused every
project path, because two env names described two roots, neither with a default, and the plugins
read the one nothing ever set.
"""

from __future__ import annotations

import ast
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from raven.core.security.tool_policy import policy_from_settings
from raven.core.workspace import allowed_roots, confine, is_within, workspace_root, workspace_source

READER_DIRS = ("raven", "ravencode", "aios", "scripts")
ROOT_NAMES = frozenset({"RAVEN_WORKSPACE", "WORKSPACE_PATH"})


def _root_env_reads() -> list[str]:
    """Every place that decides a root from an env name instead of asking the helper."""
    hits: list[str] = []
    for top in READER_DIRS:
        for path in sorted(Path(top).rglob("*.py")):
            if path.name == "workspace.py" or "raven_old" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"get", "getenv"} or not node.args:
                    continue
                first = node.args[0]
                if not (isinstance(first, ast.Constant) and first.value in ROOT_NAMES):
                    continue
                hits.append(f"{path.as_posix()}:{node.lineno}")
    return hits


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A workspace the operator never configured, so only the default under test decides."""
    monkeypatch.delenv("RAVEN_WORKSPACE", raising=False)
    monkeypatch.delenv("WORKSPACE_PATH", raising=False)
    from raven.core.config import settings

    monkeypatch.setattr(settings, "workspace_path", "")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_no_module_but_the_helper_decides_the_root_from_an_env_name() -> None:
    assert _root_env_reads() == [], _root_env_reads()


def test_the_default_root_is_the_directory_the_process_runs_in(isolated: Path) -> None:
    assert workspace_root() == isolated.resolve()
    assert workspace_source() == "the working directory"


def test_a_relative_configured_path_is_taken_from_the_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Anchoring a relative WORKSPACE_PATH at the installation directory put the workspace inside
    site-packages on a wheel install; it is a path the operator means relative to their project."""
    from raven.core.config import Settings

    monkeypatch.chdir(tmp_path)
    assert Settings.model_validate({"workspace_path": "ws"}).resolved_workspace == (tmp_path / "ws").resolve()


async def test_the_file_tools_reach_the_project_they_run_in(isolated: Path) -> None:
    from raven.plugins.files import plugin as files_plugin

    (isolated / "notes.md").write_text("# project notes\n", encoding="utf-8")
    assert "project notes" in await files_plugin.read("notes.md")
    assert "notes.md" in await files_plugin.ls(".")


def _outside_every_root(name: str) -> Path:
    """A path under neither allowed root.

    pytest's `tmp_path` lives inside the system temp directory, which the plugin layer deliberately
    permits, so a path built from it cannot prove containment. The volume anchor can, on any platform.
    """
    return Path(Path.cwd().anchor) / f"wave94-{name}"


async def test_the_confine_is_decided_at_call_time_not_at_import_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """A root frozen at import meant setting WORKSPACE_PATH changed nothing for an already-loaded plugin."""
    from raven.plugins.files import plugin as files_plugin

    first, second = _outside_every_root("first-root"), _outside_every_root("second-root")
    target = "notes.md"
    monkeypatch.setenv("RAVEN_WORKSPACE", str(first))
    with pytest.raises(FileNotFoundError):
        await files_plugin.read(str(first / target))
    monkeypatch.setenv("RAVEN_WORKSPACE", str(second))
    with pytest.raises(PermissionError, match="Access denied"):
        await files_plugin.read(str(first / target))
    with pytest.raises(FileNotFoundError):
        await files_plugin.read(str(second / target))


def test_the_policy_and_the_plugin_layer_answer_for_the_same_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two layers, one answer: what the agent path's guard allows, the tool itself has to allow too."""
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    policy = policy_from_settings()
    candidates = [
        str(tmp_path / "src" / "main.py"),
        str(Path(os.sep) / "Windows" / "system32" / "cmd.exe"),
        str(Path(tempfile.gettempdir()) / "shared.txt"),
    ]
    for candidate in candidates:
        assert policy.check_path(candidate) == is_within(candidate), candidate
    assert policy.check_path(candidates[0]) is True
    assert policy.check_path(candidates[1]) is False


def test_a_path_outside_the_root_is_refused_with_both_roots_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    with pytest.raises(PermissionError) as refused:
        confine(str(_outside_every_root("escape.txt")))
    message = str(refused.value)
    assert str(tmp_path.resolve()) in message
    assert str(Path(tempfile.gettempdir()).resolve()) in message


def test_the_allowed_roots_are_exactly_the_workspace_and_the_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    assert allowed_roots() == (tmp_path.resolve(), Path(tempfile.gettempdir()).resolve())


async def test_the_temp_directory_stays_open_when_the_workspace_is_somewhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from raven.plugins.files import plugin as files_plugin

    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    home = Path(tempfile.mkdtemp(prefix="wave94-"))
    scratch = home / "spill.txt"
    try:
        assert "bytes" in await files_plugin.write(str(scratch), "spill")
        assert await files_plugin.read(str(scratch)) == "spill"
    finally:
        shutil.rmtree(home, ignore_errors=True)


async def test_the_byte_count_a_write_reports_is_the_size_the_file_has(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`len(content)` is a character count; the tool reported it as bytes and the file disagreed."""
    from raven.plugins.files import plugin as files_plugin

    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    target = tmp_path / "cyrillic.txt"
    text = "привет мир"
    reported = await files_plugin.write(str(target), text)
    assert f"{target.stat().st_size} bytes" in reported, reported


async def test_a_git_repo_outside_the_root_is_refused_instead_of_quietly_redirected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clamping a refused repo path to the workspace returned the workspace's own log: a tool that
    answers with the wrong repository's commits is worse than one that says no."""
    from raven.tools.git import _confined_workspace

    base = tmp_path / "base"
    base.mkdir()
    monkeypatch.setenv("RAVEN_WORKSPACE", str(base))
    with pytest.raises(PermissionError, match="outside the workspace root"):
        _confined_workspace(str(tmp_path / "elsewhere"))
    assert _confined_workspace(str(base / "repo")) == (base / "repo").resolve()


def test_the_coding_agent_confines_to_the_workspace_without_the_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent's own file tools stay stricter than the plugin tools: no scratch outside the repo."""
    from ravencode.runtime.workspace import confine as agent_confine

    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    assert agent_confine("notes.md").parent == tmp_path.resolve()
    with pytest.raises(PermissionError, match="outside workspace"):
        agent_confine(str(Path(tempfile.gettempdir()) / "spill.txt"))


async def test_the_default_repository_is_the_root_not_the_process_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git status .` means this project. Sending it to the process's own directory instead answered
    from a repository the same tool would refuse by name."""
    import asyncio

    from raven.plugins.git import plugin as git_plugin

    spawned: list[dict[str, object]] = []

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"clean", b""

    async def _spawn(*args: object, **kwargs: object) -> _Proc:
        spawned.append(dict(kwargs))
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    monkeypatch.chdir(tmp_path.parent)
    assert await git_plugin.git_status(".") == "clean"
    assert spawned[0]["cwd"] == str(tmp_path.resolve())


async def test_the_test_runner_collects_from_the_root_not_the_process_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run_tests()` with no path is the operator's answer to "are we green"; pointed at the process's
    own directory it would grade whatever tree the gateway happened to start in."""
    import asyncio

    from raven.tools import tests as tests_tool

    spawned: list[list[str]] = []

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"= 1 passed in 0.01s =", b""

    async def _spawn(*args: object, **kwargs: object) -> _Proc:
        spawned.append([str(a) for a in args])
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    monkeypatch.chdir(tmp_path.parent)
    assert "1 passed" in await tests_tool.run_tests()
    assert str(tmp_path.resolve()) in spawned[0]

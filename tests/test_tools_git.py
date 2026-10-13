from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from raven.core.config import settings
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import git as git_mod
from raven.tools.git import (
    _confined_workspace,
    git_branch,
    git_branches,
    git_checkout,
    git_commit,
    git_create_pr,
    git_diff,
    git_log,
    git_pull,
    git_push,
    git_review,
    git_status,
    register_git_tools,
)


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
    (tmp_path / "test.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(tmp_path), capture_output=True, check=True)
    return tmp_path


class TestGitTools:
    def test_git_status(self, tmp_git_repo: Path) -> None:
        result = git_status(workspace=str(tmp_git_repo))
        assert isinstance(result, (dict, str))

    def test_git_log(self, tmp_git_repo: Path) -> None:
        result = git_log(count=5, workspace=str(tmp_git_repo))
        assert any("initial" in str(r) for r in result) if isinstance(result, list) else True

    def test_git_diff(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "test.txt").write_text("hello world", encoding="utf-8")
        result = git_diff(workspace=str(tmp_git_repo))
        assert isinstance(result, str)

    def test_git_branch(self, tmp_git_repo: Path) -> None:
        result = git_branch(workspace=str(tmp_git_repo))
        assert isinstance(result, (dict, str))

    async def test_git_commit(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "new.txt").write_text("new", encoding="utf-8")
        result = await git_commit(message="test commit", auto=True, workspace=str(tmp_git_repo))
        assert isinstance(result, dict)

    def test_git_push_no_remote(self, tmp_git_repo: Path) -> None:
        result = git_push(workspace=str(tmp_git_repo))
        assert isinstance(result, str)

    def test_git_pull_no_remote(self, tmp_git_repo: Path) -> None:
        result = git_pull(workspace=str(tmp_git_repo))
        assert isinstance(result, str)

    def test_register_tools(self) -> None:
        registry = ToolRegistry()
        register_git_tools(registry)
        for name in ("git_status", "git_branch", "git_log", "git_diff", "git_commit", "git_push", "git_pull"):
            assert registry.get(name) is not None


class TestConfinedWorkspace:
    def test_no_workspace_base_returns_expanded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "workspace_path", "")
        target = tmp_path / "some" / "repo"
        assert _confined_workspace(str(target)) == target.resolve()

    def test_path_outside_base_clamps_to_base(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        base = tmp_path / "base"
        base.mkdir()
        monkeypatch.setattr(settings, "workspace_path", str(base))
        assert _confined_workspace(str(tmp_path)) == base.resolve()

    def test_path_inside_base_returns_target(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        base = tmp_path / "base"
        base.mkdir()
        sub = base / "sub"
        sub.mkdir()
        monkeypatch.setattr(settings, "workspace_path", str(base))
        assert _confined_workspace(str(sub / "file.txt")) == (sub / "file.txt").resolve()

    def test_symlink_component_raises_permission_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        base = tmp_path / "base"
        base.mkdir()
        monkeypatch.setattr(settings, "workspace_path", str(base))
        link = base / "link"
        orig = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda self: str(self) == str(link))
        with pytest.raises(PermissionError):
            _confined_workspace(str(link))
        monkeypatch.setattr(Path, "is_symlink", orig)


class _FakeGit:
    def __init__(self) -> None:
        self._repo: Path | None = None
        self.run_ret: tuple[str, str] = ("out", "")
        self.run_raises: BaseException | None = None
        self.last_args: tuple[str, ...] = ()

    def status(self) -> dict[str, Any]:
        return {"clean": True}

    def get_branch(self) -> str:
        return "main"

    def is_branch(self) -> bool:
        return True

    def is_repo(self) -> bool:
        return True

    def get_log(self, count: int) -> list[dict[str, str]]:
        return [{"hash": "abc", "count": str(count)}]

    def get_diff(self, staged: bool = False) -> str:
        return "diff-text"

    def commit(self, message: str) -> Any:
        return SimpleNamespace(success=True, message=message, commit_hash="h1", error="")

    async def auto_commit_async(self) -> Any:
        return SimpleNamespace(success=True, message="auto", commit_hash="h2", error="")

    def _run(self, *args: str) -> tuple[str, str]:
        self.last_args = args
        if self.run_raises is not None:
            raise self.run_raises
        return self.run_ret

    async def create_pr_async(self, title: str = "", body: str = "") -> Any:
        return SimpleNamespace(success=True, url=f"https://pr/{title}", error="")

    async def llm_review(self, path: str | None = None) -> Any:
        comment = SimpleNamespace(file=path or "f.py", line=3, severity="low", message="nit")
        return SimpleNamespace(summary="looks fine", comments=[comment])


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch) -> _FakeGit:
    git = _FakeGit()
    monkeypatch.setattr(git_mod, "_get_git", lambda: git)
    monkeypatch.setattr(git_mod, "_confined_workspace", lambda ws: Path(ws).expanduser().resolve())
    return git


class TestGitWrappersWithFake:
    def test_status(self, fake_git: _FakeGit) -> None:
        assert git_status(workspace="/repo") == {"clean": True}

    def test_branch(self, fake_git: _FakeGit) -> None:
        assert git_branch(workspace="/repo") == {"branch": "main", "is_branch": True, "is_repo": True}

    def test_log(self, fake_git: _FakeGit) -> None:
        assert git_log(count=3, workspace="/repo") == [{"hash": "abc", "count": "3"}]

    def test_diff(self, fake_git: _FakeGit) -> None:
        assert git_diff(staged=True, workspace="/repo") == "diff-text"

    async def test_commit_non_auto(self, fake_git: _FakeGit) -> None:
        result = await git_commit(message="msg", auto=False, workspace="/repo")
        assert result == {"success": True, "message": "msg", "commit_hash": "h1", "error": ""}

    async def test_commit_auto(self, fake_git: _FakeGit) -> None:
        result = await git_commit(auto=True, workspace="/repo")
        assert result["commit_hash"] == "h2"

    def test_push_success_prefers_stdout(self, fake_git: _FakeGit) -> None:
        fake_git.run_ret = ("pushed-out", "")
        assert git_push(workspace="/repo") == "pushed-out"

    def test_push_success_falls_back_to_word(self, fake_git: _FakeGit) -> None:
        fake_git.run_ret = ("", "")
        assert git_push(workspace="/repo") == "pushed"

    def test_push_error(self, fake_git: _FakeGit) -> None:
        fake_git.run_raises = subprocess.CalledProcessError(2, "push", stderr="rejected ")
        assert git_push(workspace="/repo") == "rejected"

    def test_pull_success_prefers_stdout(self, fake_git: _FakeGit) -> None:
        fake_git.run_ret = ("fast-forward", "")
        assert git_pull(workspace="/repo") == "fast-forward"

    def test_pull_success_falls_back_to_word(self, fake_git: _FakeGit) -> None:
        fake_git.run_ret = ("", "")
        assert git_pull(workspace="/repo") == "pulled"

    def test_pull_error_no_stderr(self, fake_git: _FakeGit) -> None:
        fake_git.run_raises = subprocess.CalledProcessError(1, "pull", stderr="")
        assert git_pull(workspace="/repo") == "Pull failed (exit 1)"

    def test_branches(self, fake_git: _FakeGit) -> None:
        fake_git.run_ret = ("  main\n* dev\n\n", "")
        assert git_branches(workspace="/repo") == ["main", "* dev"]
        assert fake_git.last_args == ("branch", "-a")

    def test_checkout_existing(self, fake_git: _FakeGit) -> None:
        fake_git.run_ret = ("", "Switched to branch 'dev'")
        assert git_checkout("dev", workspace="/repo") == "Switched to branch 'dev'"
        assert fake_git.last_args == ("checkout", "dev")

    def test_checkout_create(self, fake_git: _FakeGit) -> None:
        fake_git.run_ret = ("", "")
        assert git_checkout("new", create=True, workspace="/repo") == "switched to new"
        assert fake_git.last_args == ("checkout", "-b", "new")

    async def test_create_pr(self, fake_git: _FakeGit) -> None:
        result = await git_create_pr(title="feat", body="b", workspace="/repo")
        assert result == {"success": True, "url": "https://pr/feat", "error": ""}

    async def test_review(self, fake_git: _FakeGit) -> None:
        result = await git_review(file_path="a.py", workspace="/repo")
        assert result["summary"] == "looks fine"
        assert result["comments"] == [{"file": "a.py", "line": 3, "severity": "low", "message": "nit"}]

    async def test_review_no_file_path(self, fake_git: _FakeGit) -> None:
        result = await git_review(workspace="/repo")
        assert result["comments"][0]["file"] == "f.py"


def test_register_all_wrappers() -> None:
    registry = ToolRegistry()
    register_git_tools(registry)
    for name in (
        "git_status",
        "git_branch",
        "git_log",
        "git_diff",
        "git_commit",
        "git_push",
        "git_pull",
        "git_branches",
        "git_checkout",
        "git_create_pr",
        "git_review",
    ):
        assert registry.get(name) is not None

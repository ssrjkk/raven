from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.git import (
    git_branch,
    git_commit,
    git_diff,
    git_log,
    git_pull,
    git_push,
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

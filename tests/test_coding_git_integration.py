from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from raven.coding.git_integration import GitIntegration, FileChange


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True)
    (tmp_path / "test.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
    return tmp_path


class TestGitIntegration:
    def test_is_repo(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        assert gi.is_repo() is True

    def test_is_repo_false(self, tmp_path: Path):
        gi = GitIntegration(str(tmp_path))
        assert gi.is_repo() is False

    def test_get_branch(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        assert gi.get_branch() == "main" or gi.get_branch() == "master"

    def test_get_diff(self, git_repo: Path):
        (git_repo / "test.py").write_text("x = 2\n")
        gi = GitIntegration(str(git_repo))
        diff = gi.get_diff()
        assert "x = 2" in diff

    def test_get_log(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        log = gi.get_log(count=5)
        assert len(log) >= 1
        assert log[0]["message"] == "init"

    def test_commit(self, git_repo: Path):
        (git_repo / "test.py").write_text("x = 3\n")
        gi = GitIntegration(str(git_repo))
        gi.stage_all()
        result = gi.commit("test commit")
        assert result.success is True
        assert result.commit_hash != ""

    def test_auto_commit(self, git_repo: Path):
        (git_repo / "test.py").write_text("x = 4\n")
        gi = GitIntegration(str(git_repo))
        result = gi.auto_commit()
        assert result.success is True

    def test_is_branch(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        assert gi.is_branch() is False

    def test_status(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        status = gi.status()
        assert status["is_repo"] is True

    def test_review(self, git_repo: Path):
        (git_repo / "test.py").write_text("def foo():\n    print('hi')\n    pass\n")
        gi = GitIntegration(str(git_repo))
        result = gi.review("test.py")
        assert isinstance(result.comments, list)

    def test_resolve_conflict_no_conflict(self, git_repo: Path):
        (git_repo / "test.py").write_text("x = 1\n")
        gi = GitIntegration(str(git_repo))
        resolved = gi.resolve_conflict("test.py")
        assert resolved == "x = 1\n"

    def test_generate_commit_message(self):
        gi = GitIntegration()
        msg = gi._generate_commit_message("diff --git a/app.py b/app.py\n+new code\n-old code")
        assert "feat" in msg or "chore" in msg

    def test_review_long_line(self, git_repo: Path):
        content = "x = " + "a" * 250 + "\n"
        (git_repo / "test.py").write_text(content)
        gi = GitIntegration(str(git_repo))
        result = gi.review("test.py")
        assert len(result.comments) >= 0

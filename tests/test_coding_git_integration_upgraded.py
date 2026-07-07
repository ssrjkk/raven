from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.coding.git_integration import (
    GitIntegration,
    ReviewComment,
    ReviewResult,
    _LLM_AVAILABLE,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True)
    (tmp_path / "test.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
    return tmp_path


def _mock_llm(response_text: str) -> MagicMock:
    llm = MagicMock()
    resp = AsyncMock()
    resp.content = response_text
    llm.complete = AsyncMock(return_value=resp)
    return llm


class TestGitIntegrationLLMFeatures:
    def test_constructor_accepts_llm_provider(self):
        llm = _mock_llm("feat: add new feature")
        gi = GitIntegration(llm_provider=llm)
        assert gi._llm is llm

    def test_constructor_llm_defaults_to_none(self):
        gi = GitIntegration()
        assert gi._llm is None

    @pytest.mark.asyncio
    async def test_call_llm_returns_empty_when_no_llm(self):
        gi = GitIntegration()
        result = await gi._call_llm("system", "user")
        assert result == ""

    @pytest.mark.asyncio
    async def test_call_llm_with_mock(self):
        llm = _mock_llm("some response")
        gi = GitIntegration(llm_provider=llm)
        result = await gi._call_llm("be helpful", "hello")
        assert result == "some response"
        llm.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_llm_commit_message_uses_llm(self):
        llm = _mock_llm("feat: implement user auth")
        gi = GitIntegration(llm_provider=llm)
        diff = "diff --git a/app.py b/app.py\n+def auth(): pass\n"
        msg = await gi._generate_llm_commit_message(diff)
        assert msg == "feat: implement user auth"

    @pytest.mark.asyncio
    async def test_generate_llm_commit_message_fallback(self):
        gi = GitIntegration()
        diff = "diff --git a/app.py b/app.py\n+new code\n"
        msg = await gi._generate_llm_commit_message(diff)
        assert "feat" in msg

    @pytest.mark.asyncio
    async def test_generate_llm_pr_description_uses_llm(self):
        llm = _mock_llm("## Changes\n\n- Added login")
        gi = GitIntegration(llm_provider=llm)
        diff = "diff --git a/auth.py b/auth.py\n+def login(): pass\n"
        desc = await gi._generate_llm_pr_description(diff)
        assert desc == "## Changes\n\n- Added login"

    @pytest.mark.asyncio
    async def test_generate_llm_pr_description_fallback(self):
        gi = GitIntegration()
        diff = "diff --git a/app.py b/app.py\n+new code\n-old code\n"
        desc = await gi._generate_llm_pr_description(diff)
        assert "Summary" in desc

    @pytest.mark.asyncio
    async def test_llm_review_uses_llm(self, git_repo: Path):
        llm = _mock_llm(
            '{"summary": "Looks good", "comments": [{"file": "test.py", "line": 1, "severity": "info", "message": "Consider adding type hints"}]}'
        )
        gi = GitIntegration(str(git_repo), llm_provider=llm)
        (git_repo / "test.py").write_text("def foo():\n    pass\n")
        result = await gi.llm_review("test.py")
        assert result.summary == "Looks good"
        assert len(result.comments) == 1
        assert result.comments[0].message == "Consider adding type hints"

    @pytest.mark.asyncio
    async def test_llm_review_fallback_on_no_llm(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        (git_repo / "test.py").write_text("x = " + "a" * 250 + "\n")
        result = await gi.llm_review("test.py")
        assert isinstance(result, ReviewResult)

    @pytest.mark.asyncio
    async def test_llm_review_fallback_on_bad_json(self, git_repo: Path):
        llm = _mock_llm("this is not json at all")
        gi = GitIntegration(str(git_repo), llm_provider=llm)
        (git_repo / "test.py").write_text("def foo():\n    pass\n")
        result = await gi.llm_review("test.py")
        assert isinstance(result, ReviewResult)

    @pytest.mark.asyncio
    async def test_auto_commit_async_with_llm(self, git_repo: Path):
        llm = _mock_llm("feat: add new function")
        gi = GitIntegration(str(git_repo), llm_provider=llm)
        (git_repo / "test.py").write_text("x = 42\n")
        result = await gi.auto_commit_async()
        assert result.success is True
        assert result.commit_hash != ""

    @pytest.mark.asyncio
    async def test_auto_commit_async_no_changes(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        result = await gi.auto_commit_async()
        assert result.success is False

    def test_existing_auto_commit_still_works(self, git_repo: Path):
        (git_repo / "test.py").write_text("x = 99\n")
        gi = GitIntegration(str(git_repo))
        result = gi.auto_commit()
        assert result.success is True

    def test_existing_review_still_works(self, git_repo: Path):
        (git_repo / "test.py").write_text("def foo():\n    print('hi')\n")
        gi = GitIntegration(str(git_repo))
        result = gi.review("test.py")
        assert isinstance(result.comments, list)

    def test_existing_commit_still_works(self, git_repo: Path):
        (git_repo / "test.py").write_text("x = 5\n")
        gi = GitIntegration(str(git_repo))
        gi.stage_all()
        result = gi.commit("test")
        assert result.success is True

    def test_existing_status_still_works(self, git_repo: Path):
        gi = GitIntegration(str(git_repo))
        status = gi.status()
        assert status["is_repo"] is True

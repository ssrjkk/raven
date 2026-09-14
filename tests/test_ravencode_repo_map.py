from __future__ import annotations

import time
from collections.abc import Generator
from pathlib import Path

import pytest

from ravencode.runtime.repo_map import build_repo_map, repo_map_block
from ravencode.runtime.workspace import set_workspace_root


@pytest.fixture
def sample_repo(tmp_path: Path) -> Generator[Path, None, None]:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(
        "import os\n\n\nclass Engine:\n    pass\n\n\ndef run(fast: bool) -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )
    (tmp_path / "app" / "util.py").write_text("async def fetch(url):\n    return url\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.py").write_text("def ignored():\n    pass\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "readme.md").write_text("# doc only\n", encoding="utf-8")
    yield tmp_path


class TestBuildRepoMap:
    def test_lists_files_and_symbols(self, sample_repo: Path):
        repo_map = build_repo_map(sample_repo)
        assert "- app/main.py" in repo_map
        assert "class Engine" in repo_map
        assert "def run(fast)" in repo_map
        assert "async def fetch(url)" in repo_map

    def test_excludes_junk_dirs(self, sample_repo: Path):
        repo_map = build_repo_map(sample_repo)
        assert "node_modules" not in repo_map
        assert "__pycache__" not in repo_map

    def test_broken_python_file_does_not_crash(self, sample_repo: Path):
        repo_map = build_repo_map(sample_repo)
        assert "- app/broken.py" in repo_map  # listed, just without symbols

    def test_recency_order(self, sample_repo: Path):
        old = sample_repo / "app" / "util.py"
        old_time = time.time() - 10_000
        import os

        os.utime(old, (old_time, old_time))
        repo_map = build_repo_map(sample_repo)
        assert repo_map.index("app/main.py") < repo_map.index("app/util.py")

    def test_char_budget_truncates(self, sample_repo: Path):
        repo_map = build_repo_map(sample_repo, max_chars=80)
        assert len(repo_map) <= 100
        assert "truncated" in repo_map

    def test_empty_root_returns_empty_string(self, tmp_path: Path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        assert build_repo_map(empty) == ""

    def test_missing_root_returns_empty_string(self, tmp_path: Path):
        assert build_repo_map(tmp_path / "nope") == ""

    def test_uses_workspace_root_when_none(self, sample_repo: Path):
        set_workspace_root(sample_repo)
        try:
            repo_map = build_repo_map(None)
        finally:
            set_workspace_root(None)
        assert "app/main.py" in repo_map


class TestRepoMapBlock:
    def test_block_wraps_map(self, sample_repo: Path):
        block = repo_map_block(sample_repo)
        assert block.startswith("\n\n# Repository structure")
        assert "app/main.py" in block

    def test_block_empty_when_no_repo(self, tmp_path: Path):
        assert repo_map_block(tmp_path / "nope") == ""


class TestAgentIntegration:
    def test_system_prompt_includes_repo_map(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch):
        from ravencode.runtime.agent_core import AgentConfig, ReActAgent

        set_workspace_root(sample_repo)
        try:
            agent = ReActAgent(config=AgentConfig(repo_map=True))
            prompt = agent._build_system_prompt()
        finally:
            set_workspace_root(None)
        assert "# Repository structure" in prompt
        assert "class Engine" in prompt

    def test_system_prompt_excludes_repo_map_when_disabled(self, sample_repo: Path):
        from ravencode.runtime.agent_core import AgentConfig, ReActAgent

        set_workspace_root(sample_repo)
        try:
            agent = ReActAgent(config=AgentConfig(repo_map=False))
            prompt = agent._build_system_prompt()
        finally:
            set_workspace_root(None)
        assert "# Repository structure" not in prompt

    def test_factories_enable_repo_map(self):
        from ravencode.runtime.agent_core import AgentConfig

        assert AgentConfig.safe().repo_map is True
        assert AgentConfig.fast().repo_map is True
        assert AgentConfig.autonomous().repo_map is True
        assert AgentConfig().repo_map is False

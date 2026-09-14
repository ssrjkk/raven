from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ravencode.runtime.agent_core import (
    _TOOL_CACHE_MAX_ENTRIES,
    AgentConfig,
    ReActAgent,
)
from ravencode.runtime.context import Conversation
from ravencode.runtime.tools import is_dangerous

# Mutating tools that previously slipped through as "safe" for parallel
# batching and the read-only result cache. Note: create_artifact stays
# non-dangerous (dedicated artifacts dir, no confirm required) but still
# invalidates the tool cache via _CACHE_INVALIDATING.
MUTATORS = [
    "task",
    "undo",
    "redo",
    "format_file",
    "format_files",
    "skill",
    "download_skill",
    "set_skill_registry",
    "browser_navigate",
    "browser_click",
    "browser_type",
    "canvas_render",
    "sandbox_policy",
    # already-covered baseline
    "write",
    "edit",
    "bash",
    "smart_edit",
    "patch",
    "git_commit",
]

READ_ONLY = ["read", "grep", "glob", "think", "todolist", "git_status", "git_log", "lsp_hover"]


def _patch_save(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())


class TestDangerousCoverage:
    @pytest.mark.parametrize("name", MUTATORS)
    def test_mutators_are_dangerous(self, name: str):
        assert is_dangerous(name), f"'{name}' mutates state but is not flagged dangerous"

    @pytest.mark.parametrize("name", READ_ONLY)
    def test_reads_stay_safe(self, name: str):
        assert not is_dangerous(name), f"'{name}' is read-only but flagged dangerous"


class TestProviderTimeout:
    async def test_hung_provider_times_out(self, monkeypatch: pytest.MonkeyPatch):
        _patch_save(monkeypatch)
        calls = {"n": 0}

        async def hung_provider(messages: Any) -> dict[str, Any]:
            calls["n"] += 1
            await asyncio.sleep(30)
            return {"content": "never"}

        agent = ReActAgent(
            config=AgentConfig(
                proactive_scan=False,
                diff_preview=False,
                confirm_dangerous=False,
                max_steps=3,
                llm_timeout=1,
            ),
            llm_provider=hung_provider,
        )
        result = await agent.run("t")
        assert result == "[error: LLM call timed out]"
        assert calls["n"] == 1, "timeout must not trigger retries"

    async def test_normal_provider_unaffected(self, monkeypatch: pytest.MonkeyPatch):
        _patch_save(monkeypatch)

        async def ok_provider(messages: Any) -> dict[str, Any]:
            return {"content": "fine"}

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, max_steps=3),
            llm_provider=ok_provider,
        )
        assert await agent.run("t") == "fine"


class TestToolCacheBound:
    async def test_artifact_creation_invalidates_cache(self, monkeypatch: pytest.MonkeyPatch):
        import ravencode.runtime.agent_core as ac

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False),
            conversation=Conversation(system_prompt="s"),
        )
        agent._tool_cache['read::{"path": "a"}'] = "stale"
        monkeypatch.setattr(agent, "_execute_with_retry", AsyncMock(return_value="ok"))
        item: dict[str, Any] = {
            "tc": {"id": "c1"},
            "name": "create_artifact",
            "args": {"title": "t"},
            "malformed": "",
            "emitted": True,
        }
        await agent._process_tool_item(item, 1, None, ac._ToolLoopStats())
        assert agent._tool_cache == {}, "create_artifact must invalidate cached reads"

    async def test_cache_evicts_oldest_at_cap(self, monkeypatch: pytest.MonkeyPatch):
        _patch_save(monkeypatch)

        async def fake_execute(name: str, args: dict[str, Any]) -> str:
            return "ok"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        agent = ReActAgent(
            config=AgentConfig(
                proactive_scan=False,
                diff_preview=False,
                confirm_dangerous=False,
                max_steps=3,
                use_cache=True,
            ),
        )
        for i in range(_TOOL_CACHE_MAX_ENTRIES):
            agent._tool_cache[f'read::{{"path": "f{i}"}}'] = "old"
        await agent._execute_with_retry("read", {"path": "new-file"})
        assert len(agent._tool_cache) == _TOOL_CACHE_MAX_ENTRIES
        assert 'read::{"path": "f0"}' not in agent._tool_cache
        assert agent._tool_cache['read::{"path": "new-file"}'] == "ok"


class TestTrimAccounting:
    def test_token_total_recomputed_after_trim(self):
        conv = Conversation(system_prompt="s", max_tokens=200)
        conv.add_user_message("u" * 4000)
        conv.add_assistant_tool_calls(
            [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}],
            content="",
        )
        conv.add_tool_result("c1", "r" * 4000)
        # Trimming popped the tool_calls-only assistant turn: accounting must
        # be recomputed rather than only subtracting content tokens.
        assert conv._token_total == conv._total_tokens()
        tool_msgs = [m for m in conv.messages if m.get("role") == "tool"]
        if not tool_msgs:
            # orphan dropped together with its parent — consistent state
            assert conv._token_total == conv._total_tokens()


class TestDeniedCountsAsFailure:
    async def test_denied_result_not_counted_as_success(self, monkeypatch: pytest.MonkeyPatch):
        import ravencode.runtime.agent_core as ac

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False),
            conversation=Conversation(system_prompt="s"),
        )
        monkeypatch.setattr(agent, "_confirm_action", AsyncMock(return_value=False))
        stats = ac._ToolLoopStats()
        item: dict[str, Any] = {
            "tc": {"id": "c1"},
            "name": "read",
            "args": {"path": "a"},
            "malformed": "",
            "emitted": True,
        }
        await agent._process_tool_item(item, 1, None, stats)
        assert stats.total_calls == 1
        assert stats.successful_calls == 0, "denied call must count as failure, not success"


class TestEmptyStreamGuard:
    async def test_stream_without_final_retries_and_reports(self, monkeypatch: pytest.MonkeyPatch):
        _patch_save(monkeypatch)

        class _EmptyStreamClient:
            async def ask_messages_stream(
                self, messages: list[dict[str, Any]], tools: Any = None
            ) -> Any:
                yield {"type": "token", "text": "par"}

        monkeypatch.setattr("ravencode.runtime.agent_core.AIOSClient", _EmptyStreamClient)

        async def fake_sleep(seconds: float) -> None:
            pass

        monkeypatch.setattr("ravencode.runtime.agent_core.asyncio.sleep", fake_sleep)
        agent = ReActAgent(
            config=AgentConfig(
                proactive_scan=False,
                diff_preview=False,
                confirm_dangerous=False,
                max_steps=3,
                stream_tokens=True,
            ),
        )
        result = await agent.run("t")
        assert result.startswith("[error: LLM call failed after 3 attempts")
        assert "empty LLM stream response" in result


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks require privileges on Windows")
class TestRepoMapSymlinks:
    def test_symlinked_dirs_are_skipped(self, tmp_path):
        from ravencode.runtime.repo_map import build_repo_map

        target = tmp_path / "outside"
        target.mkdir()
        (target / "leak.py").write_text("x = 1\n", encoding="utf-8")
        link = tmp_path / "loop"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("cannot create symlinks in this environment")
        repo_map = build_repo_map(tmp_path)
        assert "leak.py" not in repo_map

"""Tests for round: usage accounting, deep compaction, undo_changes, task_parallel."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.tools import MODULE_TOOLS, execute_tool, undo_changes_tool
from ravencode.runtime.workspace import set_workspace_root


def _patch_save(monkeypatch) -> None:
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())


# ---------------------------------------------------------------------------
# usage accounting
# ---------------------------------------------------------------------------


class _UsageProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        return {"content": "done", "usage": {"prompt_tokens": 100, "completion_tokens": 10}}


async def test_usage_accounting_accumulates(monkeypatch) -> None:
    _patch_save(monkeypatch)
    provider = _UsageProvider()
    agent = ReActAgent(config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, use_cache=False), llm_provider=provider)
    await agent.run("hello")
    u = agent.usage
    assert u["prompt_tokens"] == 100
    assert u["completion_tokens"] == 10
    assert u["llm_calls"] == 1
    assert "usage" in agent.dump_state()


async def test_usage_survives_missing_usage_dict(monkeypatch) -> None:
    _patch_save(monkeypatch)
    agent = ReActAgent(
        config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, use_cache=False),
        llm_provider=_UsageProvider(),
    )
    agent._record_usage({"content": "no usage here"})
    assert agent.usage["llm_calls"] == 1
    assert agent.usage["prompt_tokens"] == 0


# ---------------------------------------------------------------------------
# deep compaction
# ---------------------------------------------------------------------------


def test_compact_deep_replaces_old_tail_with_digest() -> None:
    conv = Conversation(system_prompt="sys", max_tokens=1_000_000)
    conv.add_user_message("first question about the parser")
    conv.add_assistant_message("I will fix the parser edge case now")
    conv.add_user_message("second question")
    conv.add_assistant_message("second answer detail")
    dropped = conv.compact_deep(keep_recent=2)
    assert dropped == 2
    msgs = conv.get_messages()
    assert msgs[1]["role"] == "user"
    digest = msgs[1]["content"]
    assert "[conversation digest" in digest
    assert "parser edge case" in digest
    assert "first question" in digest
    # recent messages survive intact
    assert msgs[-2]["content"] == "second question"
    assert msgs[-1]["content"] == "second answer detail"


def test_compact_deep_noop_when_short() -> None:
    conv = Conversation(system_prompt="sys")
    conv.add_user_message("only one exchange")
    assert conv.compact_deep(keep_recent=8) == 0


def test_compact_deep_reports_tool_calls_by_name() -> None:
    conv = Conversation(system_prompt="sys", max_tokens=1_000_000)
    conv.add_user_message("run it")
    conv.messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}],
        }
    )
    conv.add_tool_result("1", "output")
    conv.add_assistant_message("finished")
    conv.add_assistant_message("tail keeps me")
    conv.compact_deep(keep_recent=1)
    digest = conv.get_messages()[1]["content"]
    assert "bash" in digest


# ---------------------------------------------------------------------------
# undo_changes tool
# ---------------------------------------------------------------------------


async def test_undo_changes_without_checkpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAVENCHECKPOINT_TEST", "1")
    import ravencode.runtime.checkpoints as cp

    mgr = cp.CheckpointManager(workspace=str(tmp_path), storage_dir=str(tmp_path / "cps"))
    monkeypatch.setattr(cp, "_checkpoint_manager", mgr)
    result = await undo_changes_tool()
    assert result.startswith("[error] no checkpoint")


async def test_undo_changes_restores_modified_file(tmp_path: Path, monkeypatch) -> None:
    import ravencode.runtime.checkpoints as cp

    (tmp_path / "a.py").write_text("original", encoding="utf-8")
    mgr = cp.CheckpointManager(workspace=str(tmp_path), storage_dir=str(tmp_path / "cps"))
    monkeypatch.setattr(cp, "_checkpoint_manager", mgr)
    await mgr.save("auto: session start")

    # agent "breaks" the file
    (tmp_path / "a.py").write_text("broken!", encoding="utf-8")
    result = await undo_changes_tool()
    assert "[ok]" in result
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "original"


def test_undo_changes_registered_as_dangerous() -> None:
    assert "undo_changes" in MODULE_TOOLS
    assert MODULE_TOOLS["undo_changes"]["dangerous"] is True


async def test_auto_checkpoint_taken_at_run_start(tmp_path: Path, monkeypatch) -> None:
    import ravencode.runtime.checkpoints as cp

    (tmp_path / "b.py").write_text("keep", encoding="utf-8")
    set_workspace_root(tmp_path)
    monkeypatch.setattr(cp, "_checkpoint_manager", cp.CheckpointManager(workspace=str(tmp_path), storage_dir=str(tmp_path / "cps")))
    _patch_save(monkeypatch)
    try:
        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, use_cache=False),
            llm_provider=_UsageProvider(),
        )
        await agent.run("x")
        cps = cp.get_checkpoint_manager().list()
        assert cps and "auto: session start" in cps[0]["description"]
    finally:
        set_workspace_root(None)


# ---------------------------------------------------------------------------
# task_parallel
# ---------------------------------------------------------------------------


async def test_task_parallel_fans_out_and_orders_results(monkeypatch) -> None:
    from ravencode.agents.orchestrator import Orchestrator

    started: list[str] = []

    async def fake_delegate(task: str, **kwargs: Any) -> str:
        started.append(task)
        return f"done:{task}"

    monkeypatch.setattr(Orchestrator, "delegate", staticmethod(fake_delegate))
    result = await execute_tool("task_parallel", {"tasks": ["t1", "t2", "t3"]})
    assert "done:t1" in result
    assert "done:t3" in result
    assert result.index("t1") < result.index("t3")
    assert set(started) == {"t1", "t2", "t3"}


async def test_task_parallel_swallows_subtask_failures(monkeypatch) -> None:
    from ravencode.agents.orchestrator import Orchestrator

    async def boom(task: str, **kwargs: Any) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(Orchestrator, "delegate", staticmethod(boom))
    result = await execute_tool("task_parallel", {"tasks": ["x"]})
    assert "[error: sub-task failed" in result


async def test_task_parallel_rejects_bad_input() -> None:
    assert "[error]" in await execute_tool("task_parallel", {"tasks": []})
    assert "[error]" in await execute_tool("task_parallel", {"tasks": ["  "]})


def test_task_parallel_is_registered() -> None:
    assert MODULE_TOOLS["task_parallel"]["dangerous"] is True

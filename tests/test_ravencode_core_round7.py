"""Tests for round 7: run_tests tool, git context injection, cost estimation."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.tools import _summarize_pytest, execute_tool
from ravencode.runtime.workspace import set_workspace_root


def _patch_save(monkeypatch) -> None:
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())


class _OkProvider:
    async def __call__(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"content": "done", "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}}


# ---------------------------------------------------------------------------
# run_tests
# ---------------------------------------------------------------------------


def test_summarize_pytest_pass() -> None:
    out = "...\n========================= 5 passed in 0.42s ========================="
    result = _summarize_pytest(out, returncode=0)
    assert result.startswith("[tests PASS]")
    assert "5 passed" in result


def test_summarize_pytest_fail_lists_ids() -> None:
    out = (
        "....F\n"
        "=================================== FAILURES ===================================\n"
        "_________________________________ test_thing ___________________________________\n"
        "assert 1 == 2\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_x.py::test_thing - assert 1 == 2\n"
        "========================= 1 failed, 4 passed in 0.31s ========================="
    )
    result = _summarize_pytest(out, returncode=1)
    assert result.startswith("[tests FAIL]")
    assert "1 failed, 4 passed" in result
    assert "tests/test_x.py::test_thing" in result
    assert "FAILURES ====" not in result  # bulky sections dropped


def test_summarize_pytest_collection_crash_keeps_tail() -> None:
    out = "\n".join(f"log line {i}" for i in range(60)) + "\nImportError: cannot import name 'x'"
    result = _summarize_pytest(out, returncode=2)
    assert result.startswith("[tests FAIL]")
    assert "ImportError" in result


async def test_run_tests_on_real_mini_suite(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text(
        "def test_pass():\n    assert True\n\n\ndef test_fail():\n    assert 1 == 2\n",
        encoding="utf-8",
    )
    set_workspace_root(tmp_path)
    try:
        result = await execute_tool("run_tests", {})
        assert result.startswith("[tests FAIL]")
        assert "test_ok.py::test_fail" in result
        assert "1 failed, 1 passed" in result
    finally:
        set_workspace_root(None)


async def test_run_tests_no_tests_detected(tmp_path: Path) -> None:
    set_workspace_root(tmp_path)
    try:
        result = await execute_tool("run_tests", {})
        assert result.startswith("[error] no tests found")
    finally:
        set_workspace_root(None)


def test_run_tests_registered() -> None:
    from ravencode.runtime.tools import MODULE_TOOLS

    assert MODULE_TOOLS["run_tests"]["dangerous"] is False


# ---------------------------------------------------------------------------
# git context
# ---------------------------------------------------------------------------


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, capture_output=True)


async def test_git_context_injected_on_first_run(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    set_workspace_root(tmp_path)
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())
    try:
        seen: list[list[dict[str, Any]]] = []

        async def provider(messages: list[dict[str, Any]]) -> dict[str, Any]:
            seen.append(messages)
            return {"content": "ok"}

        agent = ReActAgent(
            config=AgentConfig(
                proactive_scan=False,
                diff_preview=False,
                confirm_dangerous=False,
                use_cache=False,
                auto_checkpoint=False,
            ),
            llm_provider=provider,
        )
        await agent.run("do something")
        await agent.run("do more")
        first_user = next(m for m in seen[0] if m["role"] == "user")
        assert "[repo context] branch" in first_user["content"]
        assert "mod.py" in first_user["content"]
        # second run must not repeat the context (history replay still
        # contains the first message, so check the newest user turn)
        second_user = [m for m in seen[-1] if m["role"] == "user"][-1]
        assert "[repo context]" not in second_user["content"]
    finally:
        set_workspace_root(None)


async def test_git_context_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    _git_init(tmp_path)
    set_workspace_root(tmp_path)
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())
    try:
        seen: list[list[dict[str, Any]]] = []

        async def provider(messages: list[dict[str, Any]]) -> dict[str, Any]:
            seen.append(messages)
            return {"content": "ok"}

        agent = ReActAgent(
            config=AgentConfig(
                proactive_scan=False,
                diff_preview=False,
                confirm_dangerous=False,
                use_cache=False,
                auto_checkpoint=False,
                git_context=False,
            ),
            llm_provider=provider,
        )
        await agent.run("hello")
        first_user = next(m for m in seen[0] if m["role"] == "user")
        assert "[repo context]" not in first_user["content"]
    finally:
        set_workspace_root(None)


# ---------------------------------------------------------------------------
# cost estimation
# ---------------------------------------------------------------------------


async def test_cost_estimated_from_token_cost(monkeypatch) -> None:
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())
    agent = ReActAgent(
        config=AgentConfig(
            proactive_scan=False,
            diff_preview=False,
            confirm_dangerous=False,
            use_cache=False,
            token_cost=(3.0, 15.0),
        ),
        llm_provider=_OkProvider(),
    )
    await agent.run("x")
    u = agent.usage
    # 1M input * $3 + 0.5M output * $15 = 3 + 7.5
    assert abs(u["cost_usd"] - 10.5) < 1e-6


async def test_no_cost_without_rates(monkeypatch) -> None:
    monkeypatch.setattr(ReActAgent, "_auto_save", AsyncMock())
    agent = ReActAgent(
        config=AgentConfig(
            proactive_scan=False, diff_preview=False, confirm_dangerous=False, use_cache=False
        ),
        llm_provider=_OkProvider(),
    )
    await agent.run("x")
    assert "cost_usd" not in agent.usage

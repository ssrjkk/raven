from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from loguru import logger

from ravencode.runtime.agent_core import ReActAgent


class AgentType(StrEnum):
    PLANNER = "planner"
    CODER = "coder"
    DEBUGGER = "debugger"
    AUTONOMOUS = "autonomous"


@dataclass
class AgentResult:
    agent: str
    success: bool
    data: Any = None
    error: str | None = None
    steps: int = 0


class Orchestrator:
    def __init__(self) -> None:
        self.memory: list[dict[str, Any]] = field(default_factory=list)

    def _build_agent(self, system_prompt: str | None = None) -> ReActAgent:
        return ReActAgent(system_prompt=system_prompt)

    async def dispatch(self, task: str, agent_type: AgentType) -> AgentResult:
        try:
            dispatch_map = {
                AgentType.PLANNER: self._run_planner,
                AgentType.CODER: self._run_coder,
                AgentType.DEBUGGER: self._run_debugger,
                AgentType.AUTONOMOUS: self._run_autonomous_loop,
            }
            handler = dispatch_map.get(agent_type)
            if handler is None:
                return AgentResult(agent=agent_type.value, success=False, error=f"Unknown agent: {agent_type}")
            return await handler(task)
        except Exception as exc:
            logger.exception("Agent dispatch failed")
            return AgentResult(agent=agent_type.value, success=False, error=str(exc))

    async def _run_planner(self, task: str) -> AgentResult:
        agent = self._build_agent(
            system_prompt="You are a planning agent. Analyze the task and create a detailed step-by-step plan. "
            "Use tools to explore the codebase and understand what needs to be done."
        )
        result = await agent.run(task)
        return AgentResult(agent="planner", success=True, data={"plan": result}, steps=agent._context.message_count)

    async def _run_coder(self, task: str) -> AgentResult:
        agent = self._build_agent(
            system_prompt="You are a coding agent. Write, edit, and refactor code. Always explore existing code "
            "before making changes. Use read/glob/grep to understand the codebase first."
        )
        result = await agent.run(task)
        return AgentResult(agent="coder", success=True, data={"code_result": result}, steps=agent._context.message_count)

    @staticmethod
    async def _run_debugger(task: str) -> AgentResult:
        agent = ReActAgent(
            system_prompt="You are a debugging agent. Diagnose issues in code by examining file contents, "
            "running tests, and analyzing error messages. Use bash to run tests when needed."
        )
        result = await agent.run(task)
        return AgentResult(agent="debugger", success=True, data={"debug_result": result})

    async def _run_autonomous_loop(self, task: str) -> AgentResult:
        agent = self._build_agent()
        result = await agent.run(task)
        return AgentResult(agent="autonomous", success=True, data={"result": result}, steps=agent._context.message_count)

    async def delegate(self, task: str, context: str | None = None) -> str:
        agent = ReActAgent(
            system_prompt=(
                "You are a sub-agent handling a delegated task. Complete it efficiently and return the result. "
                f"{'Context: ' + context if context else ''}"
            ),
            max_steps=15,
        )
        return await agent.run(task)

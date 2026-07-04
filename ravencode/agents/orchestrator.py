from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.context import Conversation


class AgentType(StrEnum):
    PLANNER = "planner"
    PLANNER_READONLY = "planner_readonly"
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
        self._agent_cache: dict[str, Any] = {}

    @staticmethod
    def _build_agent(
        system_prompt: str | None = None,
        max_steps: int | None = None,
        memory_path: str | None = None,
        plan_mode: bool = False,
    ) -> ReActAgent:
        config = AgentConfig(memory_path=memory_path, max_steps=max_steps or 30, plan_mode=plan_mode)
        conv = Conversation(system_prompt=system_prompt) if system_prompt else None
        return ReActAgent(config=config, conversation=conv)

    @staticmethod
    def _build_with_override(
        agent_config_override: AgentConfig | None,
        system_prompt: str | None = None,
        memory_path: str | None = None,
    ) -> ReActAgent:
        if agent_config_override is not None:
            conv = Conversation(system_prompt=system_prompt) if system_prompt else None
            return ReActAgent(config=agent_config_override, conversation=conv)
        return Orchestrator._build_agent(system_prompt=system_prompt, memory_path=memory_path)

    async def dispatch(
        self,
        task: str,
        agent_type: AgentType,
        memory_path: str | None = None,
        agent_config_override: AgentConfig | None = None,
    ) -> AgentResult:
        try:
            dispatch_map = {
                AgentType.PLANNER: self._run_planner,
                AgentType.PLANNER_READONLY: self._run_planner_readonly,
                AgentType.CODER: self._run_coder,
                AgentType.DEBUGGER: self._run_debugger,
                AgentType.AUTONOMOUS: self._run_autonomous_loop,
            }
            handler = dispatch_map.get(agent_type)
            if handler is None:
                return AgentResult(agent=agent_type.value, success=False, error=f"Unknown agent: {agent_type}")
            return await handler(task, memory_path=memory_path, agent_config_override=agent_config_override)
        except Exception as exc:
            logger.exception("Agent dispatch failed")
            return AgentResult(agent=agent_type.value, success=False, error=str(exc))

    async def _run_planner(self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None) -> AgentResult:
        agent = self._build_with_override(
            agent_config_override,
            system_prompt="You are a planning agent. Analyze the task and create a detailed step-by-step plan. "
            "Use tools to explore the codebase and understand what needs to be done.",
            memory_path=memory_path,
        )
        result = await agent.run(task)
        return AgentResult(agent="planner", success=True, data={"plan": result}, steps=agent.conversation.message_count)

    async def _run_planner_readonly(self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None) -> AgentResult:
        if agent_config_override:
            cfg = agent_config_override
        else:
            cfg = AgentConfig(memory_path=memory_path, plan_mode=True)
        conv = Conversation(
            system_prompt="You are a read-only planning agent. You analyze tasks and create plans. "
            "You MUST NOT modify any files or execute commands."
        )
        agent = ReActAgent(config=cfg, conversation=conv)
        result = await agent.run(task)
        return AgentResult(agent="planner_readonly", success=True, data={"plan": result}, steps=agent.conversation.message_count)

    async def _run_coder(self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None) -> AgentResult:
        agent = self._build_with_override(
            agent_config_override,
            system_prompt="You are a coding agent. Write, edit, and refactor code. Always explore existing code "
            "before making changes. Use read/glob/grep to understand the codebase first.",
            memory_path=memory_path,
        )
        result = await agent.run(task)
        return AgentResult(agent="coder", success=True, data={"code_result": result}, steps=agent.conversation.message_count)

    async def _run_debugger(self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None) -> AgentResult:
        if agent_config_override:
            config = agent_config_override
        else:
            config = AgentConfig(memory_path=memory_path)
        agent = ReActAgent(
            config=config,
            conversation=Conversation(
                system_prompt="You are a debugging agent. Diagnose issues in code by examining file contents, "
                "running tests, and analyzing error messages. Use bash to run tests when needed."
            ),
        )
        result = await agent.run(task)
        return AgentResult(agent="debugger", success=True, data={"debug_result": result})

    async def _run_autonomous_loop(self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None) -> AgentResult:
        agent = self._build_with_override(agent_config_override, memory_path=memory_path)
        result = await agent.run(task)
        return AgentResult(agent="autonomous", success=True, data={"result": result}, steps=agent.conversation.message_count)

    @staticmethod
    async def delegate(task: str, context: str | None = None, memory_path: str | None = None) -> str:
        prompt = "You are a sub-agent handling a delegated task. Complete it efficiently and return the result."
        if context:
            prompt += f"\nContext: {context}"
        config = AgentConfig(memory_path=memory_path, max_steps=15)
        agent = ReActAgent(
            config=config,
            conversation=Conversation(system_prompt=prompt),
        )
        return await agent.run(task)

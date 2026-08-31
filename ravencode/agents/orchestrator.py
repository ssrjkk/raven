from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from ravencode.config.loader import RavenConfig, get_config
from ravencode.core.prompts import get_prompt
from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.permissions import PermissionManager


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
        logger.debug("Orchestrator initialized")

    @staticmethod
    def _build_agent(
        system_prompt: str | None = None,
        max_steps: int | None = None,
        memory_path: str | None = None,
        plan_mode: bool = False,
        raven_config: RavenConfig | None = None,
    ) -> ReActAgent:
        cfg = raven_config or get_config()
        pm = PermissionManager.from_dict(cfg.permissions) if cfg.permissions else None
        config = AgentConfig(
            memory_path=memory_path,
            max_steps=max_steps or cfg.max_steps,
            plan_mode=plan_mode or cfg.plan_mode,
            auto_format=cfg.auto_format,
            use_cache=cfg.use_cache,
            confirm_dangerous=cfg.confirm_dangerous,
            diff_preview=cfg.diff_preview,
            proactive_scan=cfg.proactive_scan,
            permissions=pm,
        )
        conv = Conversation(system_prompt=system_prompt) if system_prompt else None
        return ReActAgent(config=config, conversation=conv)

    @staticmethod
    def _build_with_override(
        agent_config_override: AgentConfig | None,
        system_prompt: str | None = None,
        memory_path: str | None = None,
        raven_config: RavenConfig | None = None,
    ) -> ReActAgent:
        if agent_config_override is not None:
            conv = Conversation(system_prompt=system_prompt) if system_prompt else None
            return ReActAgent(config=agent_config_override, conversation=conv)
        return Orchestrator._build_agent(
            system_prompt=system_prompt,
            memory_path=memory_path,
            raven_config=raven_config,
        )

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
                return AgentResult(agent=str(agent_type), success=False, error=f"Unknown agent: {agent_type}")
            return await handler(task, memory_path=memory_path, agent_config_override=agent_config_override)
        except Exception as exc:
            logger.exception("Agent dispatch failed")
            return AgentResult(agent=str(agent_type), success=False, error=str(exc))

    async def _run_planner(
        self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None
    ) -> AgentResult:
        agent = self._build_with_override(
            agent_config_override,
            system_prompt=get_prompt("planner"),
            memory_path=memory_path,
        )
        result = await agent.run(task)
        return AgentResult(agent="planner", success=True, data={"plan": result}, steps=agent.conversation.message_count)

    async def _run_planner_readonly(
        self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None
    ) -> AgentResult:
        if agent_config_override:
            cfg = agent_config_override
        else:
            cfg = AgentConfig(memory_path=memory_path, plan_mode=True)
        conv = Conversation(system_prompt=get_prompt("planner_readonly"))
        agent = ReActAgent(config=cfg, conversation=conv)
        result = await agent.run(task)
        return AgentResult(
            agent="planner_readonly", success=True, data={"plan": result}, steps=agent.conversation.message_count
        )

    async def _run_coder(
        self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None
    ) -> AgentResult:
        agent = self._build_with_override(
            agent_config_override,
            system_prompt=get_prompt("coder"),
            memory_path=memory_path,
        )
        result = await agent.run(task)

        is_failure = (
            result.startswith("[error]")
            or result.startswith("[validation_error]")
            or result.startswith("[aborted]")
            or "I cannot" in result
            or "I'm unable" in result
        )
        if is_failure and not agent_config_override:
            logger.info("Coder failed, escalating to debugger")
            debugger_result = await self._run_debugger(
                task=f"Coder failed with: {result}\nOriginal task: {task}",
                memory_path=memory_path,
                agent_config_override=agent_config_override,
            )
            debugger_result.agent = "coder(+debugger)"
            debugger_result.data = {"code_result": result, "debug_result": debugger_result.data}
            return debugger_result

        return AgentResult(
            agent="coder", success=True, data={"code_result": result}, steps=agent.conversation.message_count
        )

    async def _run_debugger(
        self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None
    ) -> AgentResult:
        if agent_config_override:
            config = agent_config_override
        else:
            config = AgentConfig(memory_path=memory_path)
        agent = ReActAgent(
            config=config,
            conversation=Conversation(
                system_prompt=get_prompt("debugger"),
            ),
        )
        result = await agent.run(task)
        return AgentResult(agent="debugger", success=True, data={"debug_result": result})

    async def _run_autonomous_loop(
        self, task: str, memory_path: str | None = None, agent_config_override: AgentConfig | None = None
    ) -> AgentResult:
        agent = self._build_with_override(agent_config_override, memory_path=memory_path)
        result = await agent.run(task)

        needs_verify = any(
            marker in result
            for marker in (
                "[error]",
                "[validation_error]",
                "[aborted]",
                "I cannot",
                "I'm unsure",
                "verification failed",
            )
        )
        if needs_verify and not agent_config_override:
            logger.info("Autonomous agent produced uncertain result, running self-check")
            verify_agent = self._build_with_override(
                agent_config_override,
                system_prompt=get_prompt("debugger"),
                memory_path=memory_path,
            )
            verification = await verify_agent.run(
                f"Verify the following result is correct and complete. "
                f"Report any issues found.\n\nResult:\n{result}"
            )
            if verification.strip().startswith("[issues]"):
                return AgentResult(
                    agent="autonomous",
                    success=False,
                    data={"result": result, "verification": verification},
                    steps=agent.conversation.message_count,
                )

        return AgentResult(
            agent="autonomous", success=True, data={"result": result}, steps=agent.conversation.message_count
        )

    @staticmethod
    async def delegate(task: str, context: str | None = None, memory_path: str | None = None) -> str:
        task_lower = task.lower()
        if any(w in task_lower for w in ("debug", "error", "crash", "fix", "bug", "failing")):
            role = "debugger"
            prompt = get_prompt("debugger")
        elif any(w in task_lower for w in ("review", "check", "lint", "quality", "audit", "verify", "validate", "test", "confirm")):
            role = "verifier"
            prompt = get_prompt("verifier")
        elif any(w in task_lower for w in ("plan", "break down", "decompose", "roadmap", "steps")):
            role = "planner"
            prompt = get_prompt("planner")
        elif any(w in task_lower for w in ("write", "implement", "create", "code", "refactor", "add feature")):
            role = "coder"
            prompt = get_prompt("coder")
        else:
            role = "delegate"
            prompt = get_prompt("delegate")

        if context:
            prompt += f"\nContext: {context}"
        logger.debug("Orchestrator.delegate: task → role='{}'", role)
        config = AgentConfig(memory_path=memory_path, max_steps=15)
        agent = ReActAgent(
            config=config,
            conversation=Conversation(system_prompt=prompt),
        )
        return await agent.run(task)

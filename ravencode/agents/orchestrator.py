from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger


class AgentType(str, Enum):
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


class Orchestrator:
    def __init__(self) -> None:
        self.memory: list[dict[str, Any]] = field(default_factory=list)

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
        from raven.core.task_engine.planner import TaskPlanner

        tools = None
        try:
            from raven.tools.register_all import create_tool_registry

            tools = create_tool_registry()
        except ImportError:
            logger.warning("Tool registry unavailable")
        except Exception as exc:
            logger.warning("Tool registry init failed: {}", exc)

        llm = None
        try:
            from raven.core.llm import LLMRouter

            llm = LLMRouter()
        except Exception as exc:
            logger.error("LLM unavailable (no API keys?): {}", exc)
            return AgentResult(agent="planner", success=False, error=f"LLM unavailable: {exc}")

        planner = TaskPlanner(tools=tools) if tools else TaskPlanner(tools=tools)  # type: ignore[arg-type]
        plan = await planner.plan(task, llm=llm)
        return AgentResult(agent="planner", success=True, data={"plan": str(plan)})

    async def _run_coder(self, task: str) -> AgentResult:
        import uuid
        import time

        try:
            from raven.core.coder.models import CodingSession, SessionStatus
            from raven.core.coder.session import CodingSessionManager
            from raven.core.config import settings

            db_path = settings.resolved_db_path
            mgr = CodingSessionManager(str(db_path))
            session = CodingSession(
                id=str(uuid.uuid4()),
                goal=task,
                status=SessionStatus.ACTIVE,
                created_at=time.time(),
                updated_at=time.time(),
            )
            created = mgr.create_session(session)
            session_id = str(getattr(created, "id", created))
            self.memory.append({"type": "code", "task": task, "session": session_id})
            return AgentResult(agent="coder", success=True, data={"session_id": session_id})
        except Exception as exc:
            logger.error("Coder failed: {}", exc)
            return AgentResult(agent="coder", success=False, error=str(exc))

    @staticmethod
    async def _run_debugger(task: str) -> AgentResult:
        try:
            from raven.core.coder.review import CodeReviewer

            reviewer = CodeReviewer()
            comments = await reviewer.review_file(file_path="input", content=task, language="python")
            return AgentResult(
                agent="debugger",
                success=True,
                data={"issues": [c.message for c in comments]},
            )
        except Exception as exc:
            logger.error("Debugger failed: {}", exc)
            return AgentResult(agent="debugger", success=False, error=str(exc))

    async def _run_autonomous_loop(self, task: str) -> AgentResult:
        max_steps = 25
        results = []
        for step in range(max_steps):
            result = await self._run_planner(f"{task} (step {step + 1})")
            if not result.success:
                return AgentResult(agent="autonomous", success=False, error=result.error)
            results.append(result.data)
            if len(results) > 1 and results[-1] == results[-2]:
                break
        return AgentResult(
            agent="autonomous",
            success=True,
            data={"steps_completed": len(results), "completed": True},
        )

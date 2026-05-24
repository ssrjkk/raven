from enum import Enum
from typing import Any
from loguru import logger

from raven.core.config import settings


class AgentType(Enum):
    PLANNER = "planner"
    CODER = "coder"
    DEBUGGER = "debugger"
    AUTONOMOUS = "autonomous"


class Orchestrator:
    def __init__(self):
        self.memory: list[dict[str, Any]] = []

    async def dispatch(self, task: str, agent_type: AgentType) -> dict[str, Any]:
        try:
            dispatch_map = {
                AgentType.PLANNER: self._run_planner,
                AgentType.CODER: self._run_coder,
                AgentType.DEBUGGER: self._run_debugger,
                AgentType.AUTONOMOUS: self._run_autonomous_loop,
            }
            handler = dispatch_map.get(agent_type)
            if handler is None:
                return {"error": f"Unknown agent type: {agent_type}"}
            return await handler(task)
        except Exception as exc:
            logger.exception("Agent dispatch failed")
            return {"agent": agent_type.value, "error": str(exc)}

    async def _run_planner(self, task: str) -> dict[str, Any]:
        from raven.core.task_engine.planner import TaskPlanner
        from raven.core.llm import LLMRouter
        from raven.tools.register_all import create_tool_registry
        tools = create_tool_registry()
        planner = TaskPlanner(tools)
        llm = LLMRouter()
        plan = await planner.plan(task, llm=llm)
        self.memory.append({"type": "plan", "task": task, "plan": plan})
        return {"agent": "planner", "plan": plan}

    async def _run_coder(self, task: str) -> dict[str, Any]:
        from raven.core.coder.session import CodingSessionManager
        from raven.core.coder.models import CodingSession, SessionStatus
        import time
        import uuid

        try:
            db_path = settings.resolved_db_path
        except AttributeError:
            db_path = "data/sessions.db"
        coder = CodingSessionManager(str(db_path))
        session = CodingSession(
            id=str(uuid.uuid4()),
            goal=task,
            status=SessionStatus.ACTIVE,
            created_at=time.time(),
            updated_at=time.time(),
        )
        created = coder.create_session(session)
        session_id = str(getattr(created, "id", created))
        self.memory.append({"type": "code", "task": task, "session": session_id})
        return {"agent": "coder", "session_id": session_id}

    async def _run_debugger(self, task: str) -> dict[str, Any]:
        from raven.core.coder.review import CodeReviewer
        reviewer = CodeReviewer()
        comments = await reviewer.review_file(file_path="input", content=task, language="python")
        self.memory.append({"type": "debug", "task": task, "comments": len(comments)})
        return {"agent": "debugger", "issues": [c.message for c in comments]}

    async def _run_autonomous_loop(self, task: str) -> dict[str, Any]:
        max_steps = 25
        results = []
        for step in range(max_steps):
            plan = await self._run_planner(f"{task} (step {step + 1})")
            results.append(plan)
            if step > 0 and results[-1] == results[-2]:
                break
        return {"agent": "autonomous", "steps": len(results), "completed": True}

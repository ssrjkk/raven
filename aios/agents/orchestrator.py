"""
Agent Orchestrator — dispatches tasks to Raven's agent subsystems.

Routes tasks to planner, coder, debugger, or autonomous loop.
"""

from enum import Enum
from typing import Any
from pathlib import Path
from raven.core.config import settings


class AgentType(Enum):
    PLANNER = "planner"
    CODER = "coder"
    DEBUGGER = "debugger"
    AUTONOMOUS = "autonomous"


class Orchestrator:
    """Routes tasks to the right Raven agent backend."""

    def __init__(self):
        self.memory: list[dict[str, Any]] = []

    async def dispatch(self, task: str, agent_type: AgentType) -> dict[str, Any]:
        if agent_type == AgentType.PLANNER:
            return await self._run_planner(task)
        elif agent_type == AgentType.CODER:
            return await self._run_coder(task)
        elif agent_type == AgentType.DEBUGGER:
            return await self._run_debugger(task)
        elif agent_type == AgentType.AUTONOMOUS:
            return await self._run_autonomous_loop(task)
        return {"error": f"Unknown agent type: {agent_type}"}

    async def _run_planner(self, task: str) -> dict[str, Any]:
        from raven.core.task_engine.planner import TaskPlanner
        from raven.tools.register_all import create_tool_registry
        tools = create_tool_registry()
        planner = TaskPlanner(tools)
        plan = await planner.plan(task)
        self.memory.append({"type": "plan", "task": task, "plan": plan})
        return {"agent": "planner", "plan": plan}

    async def _run_coder(self, task: str) -> dict[str, Any]:
        from raven.core.coder.session import CodingSessionManager
        from raven.core.coder.models import CodingSession, SessionStatus
        import time, uuid
        db_path = str(settings.resolved_db_path)
        coder = CodingSessionManager(db_path)
        session = CodingSession(
            id=str(uuid.uuid4()),
            goal=task,
            status=SessionStatus.ACTIVE,
            created_at=time.time(),
            updated_at=time.time(),
        )
        created = coder.create_session(session)
        self.memory.append({"type": "code", "task": task, "session": created.id if hasattr(created, 'id') else str(created)})
        return {"agent": "coder", "session_id": created.id if hasattr(created, 'id') else str(created)}

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

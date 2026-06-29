from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from loguru import logger

from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.context import Conversation


@dataclass
class SessionInfo:
    id: str
    name: str
    status: str
    agent_type: str
    created_at: str
    message_count: int
    step_count: int


class ManagedSession:
    def __init__(self, sid: str, name: str, agent: ReActAgent) -> None:
        self.id = sid
        self.name = name
        self.agent = agent
        self.status = "idle"
        self.created_at = datetime.now(UTC).isoformat()
        self.message_count = 0
        self.step_count = 0
        self._task: asyncio.Task[str] | None = None

    @property
    def info(self) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            name=self.name,
            status=self.status,
            agent_type=self.agent.name,
            created_at=self.created_at,
            message_count=self.message_count,
            step_count=self.step_count,
        )

    async def run(self, user_input: str) -> str:
        self.status = "running"
        self.message_count += 1
        on_step = self.agent.config.on_step

        async def _count_step(msg: str, step: int) -> None:
            self.step_count = step
            if on_step:
                await on_step(msg, step)

        self.agent.config.on_step = _count_step
        try:
            self._task = asyncio.create_task(self.agent.run(user_input))
            result = await self._task
            self.status = "idle"
            return result
        except asyncio.CancelledError:
            self.status = "idle"
            return "[cancelled]"
        except Exception as exc:
            self.status = "idle"
            logger.exception("Session {} failed: {}", self.id, exc)
            return f"[error: {exc}]"

    def abort(self) -> None:
        self.agent.abort()


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = asyncio.Lock()

    @property
    def sessions(self) -> list[SessionInfo]:
        return [s.info for s in self._sessions.values()]

    async def create(
        self,
        name: str = "",
        system_prompt: str | None = None,
        agent_type: str = "raven",
        max_steps: int = 30,
        confirm_dangerous: bool = True,
    ) -> ManagedSession:
        sid = uuid.uuid4().hex[:12]
        name = name or f"session-{sid[:8]}"

        config = AgentConfig(
            max_steps=max_steps,
            confirm_dangerous=confirm_dangerous,
            diff_preview=True,
            proactive_scan=True,
            auto_format=True,
        )

        conv = Conversation(system_prompt=system_prompt) if system_prompt else None
        agent = ReActAgent(config=config, conversation=conv, name=agent_type)
        session = ManagedSession(sid, name, agent)

        async with self._lock:
            self._sessions[sid] = session

        logger.info("Session created: {} ({})", sid, name)
        return session

    async def get(self, sid: str) -> ManagedSession | None:
        async with self._lock:
            return self._sessions.get(sid)

    async def remove(self, sid: str) -> bool:
        async with self._lock:
            session = self._sessions.pop(sid, None)
        if session:
            session.abort()
            logger.info("Session removed: {}", sid)
            return True
        return False

    async def abort_all(self) -> None:
        async with self._lock:
            for session in self._sessions.values():
                session.abort()

    async def cleanup(self) -> None:
        await self.abort_all()
        self._sessions.clear()


_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager

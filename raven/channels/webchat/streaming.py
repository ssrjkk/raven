from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from loguru import logger

from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter, ReActAgent


class AgentStreamHandler:
    """Bridges ReActAgent events to a WebSocket."""

    def __init__(self, websocket: WebSocket, session_id: str) -> None:
        self._ws = websocket
        self._session_id = session_id
        self._ee = EventEmitter()

    def build_event_emitter(self) -> EventEmitter:
        ee = EventEmitter()
        ee.on("step_start", self._on_step_start)
        ee.on("tool_call", self._on_tool_call)
        ee.on("tool_result", self._on_tool_result)
        ee.on("message", self._on_message)
        ee.on("done", self._on_done)
        return ee

    async def _send(self, msg: dict[str, Any]) -> None:
        try:
            await self._ws.send_json(msg)
        except Exception:
            logger.debug("Stream send failed (client disconnected)")

    async def _on_step_start(self, event: AgentEvent) -> None:
        await self._send({
            "type": "step_start",
            "session_id": self._session_id,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    async def _on_tool_call(self, event: AgentEvent) -> None:
        await self._send({
            "type": "tool_call",
            "session_id": self._session_id,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    async def _on_tool_result(self, event: AgentEvent) -> None:
        await self._send({
            "type": "tool_result",
            "session_id": self._session_id,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    async def _on_message(self, event: AgentEvent) -> None:
        await self._send({
            "type": "message",
            "session_id": self._session_id,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    async def _on_done(self, event: AgentEvent) -> None:
        await self._send({
            "type": "done",
            "session_id": self._session_id,
            "data": event.data,
            "timestamp": event.timestamp,
        })

    async def handle_message(self, text: str) -> str:
        config = AgentConfig(
            max_steps=30,
            event_emitter=self.build_event_emitter(),
            diff_preview=True,
            proactive_scan=True,
        )
        agent = ReActAgent(config=config)
        result = await agent.run(text)
        return result

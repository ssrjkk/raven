"""Session persistence — auto-save/restore agent sessions between runs."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.context import Conversation


class SessionStore:
    def __init__(self, storage_dir: str = "data/sessions") -> None:
        self._storage = Path(storage_dir).expanduser().resolve()
        self._storage.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._storage / f"{session_id}.json"

    def list(self) -> list[dict[str, Any]]:
        sessions = []
        for f in self._storage.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "id": f.stem,
                    "created": data.get("created", 0),
                    "updated": data.get("updated", 0),
                    "summary": data.get("summary", ""),
                    "steps": data.get("steps", 0),
                })
            except (json.JSONDecodeError, OSError):
                continue
        return sorted(sessions, key=lambda s: s["updated"], reverse=True)

    async def save(self, agent: ReActAgent, summary: str = "") -> str:
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        state = agent.dump_state()
        state["summary"] = summary
        state["created"] = time.time()
        state["updated"] = time.time()
        state["steps"] = agent.conversation.message_count
        p = self._path(session_id)
        data = json.dumps(state, ensure_ascii=False, indent=2)
        tmp = p.with_suffix(".tmp")
        await asyncio.to_thread(tmp.write_text, data, encoding="utf-8")
        tmp.rename(p)
        logger.info("Session saved: {}", session_id)
        return session_id

    async def load(self, session_id: str) -> ReActAgent | None:
        p = self._path(session_id)
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load session {}: {}", session_id, exc)
            return None
        cfg = AgentConfig(**data.get("config", {}))
        conv = Conversation(messages=data.get("conversation", []))
        agent = ReActAgent(config=cfg, conversation=conv, name=data.get("name", "raven"))
        data["updated"] = time.time()
        await asyncio.to_thread(p.write_text, json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return agent

    async def delete(self, session_id: str) -> bool:
        p = self._path(session_id)
        if p.is_file():
            p.unlink()
            return True
        return False


_session_store: SessionStore | None = None


def get_session_store(storage_dir: str = "data/sessions") -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore(storage_dir=storage_dir)
    return _session_store


async def session_save(agent: ReActAgent, summary: str = "") -> str:
    return await get_session_store().save(agent, summary)


async def session_load(session_id: str) -> ReActAgent | None:
    return await get_session_store().load(session_id)

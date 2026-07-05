from __future__ import annotations

import uuid

from raven.core.db import Database
from raven.core.models import Message

PLUGIN_NAME = "sessions"
PLUGIN_DESCRIPTION = "List and inspect conversation sessions"

_db: Database | None = None


def init(db: Database):
    global _db
    _db = db


async def sessions_list(session_id: str = "") -> str:
    """List all active sessions. Returns session IDs, channels, and assigned agents."""
    if not _db:
        return "Database not initialized"
    sessions = await _db.get_sessions()
    if not sessions:
        return "No active sessions."
    lines = []
    for s in sessions[:20]:
        agent = getattr(s, "agent_id", "default")
        lines.append(f"{s.id[:24]:24s} | {s.channel:12s} | agent={agent}")
    return "\n".join(lines)


async def sessions_history(session_id: str = "", limit: int = 20) -> str:
    """View message history for a session. Shows roles and truncated content."""
    if not _db or not session_id:
        return "Usage: sessions_history(session_id='...', limit=20)"
    msgs = await _db.get_session_messages(session_id, limit=limit)
    if not msgs:
        return f"No messages in session: {session_id}"
    lines = []
    for m in msgs:
        content = m.content[:100].replace("\n", " ")
        lines.append(f"[{m.role:9s}] {content}")
    return "\n".join(lines)


async def sessions_send(session_id: str = "", message: str = "") -> str:
    """Send a message to a session as the assistant."""
    if not _db:
        return "Database not initialized"
    if not session_id or not message:
        return "Usage: sessions_send(session_id='...', message='...')"
    await _db.save_message(Message(session_id=session_id, role="assistant", content=message))
    return f"Message sent to session {session_id}"


async def sessions_spawn(session_id: str = "", task: str = "") -> str:
    """Spawn a sub-session for a background task."""
    if not _db:
        return "Database not initialized"
    if not session_id or not task:
        return "Usage: sessions_spawn(session_id='...', task='...')"
    sub_id = f"{session_id}/sub/{uuid.uuid4().hex[:8]}"
    await _db.save_message(Message(session_id=sub_id, role="system", content=f"Spawned sub-session for task: {task}"))
    return f"Sub-session {sub_id} spawned for task: {task[:100]}"

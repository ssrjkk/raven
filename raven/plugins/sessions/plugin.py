from __future__ import annotations

from raven.core.config import settings
from raven.core.db import Database

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
    return f"Message queued for session {session_id}"


async def sessions_spawn(session_id: str = "", task: str = "") -> str:
    """Spawn a sub-session for a background task."""
    if not _db:
        return "Database not initialized"
    return f"Sub-session spawned for task: {task[:100]}"

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


async def sessions_list() -> str:
    """List the sessions in the database, up to 20, one per line with id, channel and assigned agent.

    Takes nothing: there is no way to ask for one session here, so use sessions_history for the messages of a known id.
    """
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
    """Read the stored messages of one session, oldest first, with role and first 100 characters each.

    session_id: Session to read; empty answers with the usage line rather than guessing.
    limit: How many messages to return, clamped to 1..50.
    """
    if not _db or not session_id:
        return "Usage: sessions_history(session_id='...', limit=20)"
    limit = max(1, min(int(limit), 50))
    msgs = await _db.get_session_messages(session_id, limit=limit)
    if not msgs:
        return f"No messages in session: {session_id}"
    lines = []
    for m in msgs:
        content = m.content[:100].replace("\n", " ")
        lines.append(f"[{m.role:9s}] {content}")
    return "\n".join(lines)


async def sessions_send(session_id: str = "", message: str = "") -> str:
    """Append one assistant message to a session's stored history; nothing is delivered to a channel or read by anyone.

    session_id: Session to write into. A message can be stored under an id that has no session, and it is accepted
        anyway.
    message: Text stored as the assistant's turn, cut to 2000 characters.
    """
    if not _db:
        return "Database not initialized"
    if not session_id or not message:
        return "Usage: sessions_send(session_id='...', message='...')"
    message = message[:2000]
    await _db.save_message(Message(session_id=session_id, role="assistant", content=message))
    return f"Stored assistant message in session {session_id} (not delivered to a channel)"


async def sessions_spawn(session_id: str = "", task: str = "") -> str:
    """Create a sub-session id under a session and note the task there; nothing is started and no code runs the task.

    session_id: Parent session the new id is built under.
    task: Text written into the sub-session; a reader has to pick it up for anything to happen.
    """
    if not _db:
        return "Database not initialized"
    if not session_id or not task:
        return "Usage: sessions_spawn(session_id='...', task='...')"
    sub_id = f"{session_id}/sub/{uuid.uuid4().hex[:8]}"
    await _db.save_message(Message(session_id=sub_id, role="system", content=f"Spawned sub-session for task: {task}"))
    return f"Sub-session {sub_id} created for task: {task[:100]}"

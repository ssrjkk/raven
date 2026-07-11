from __future__ import annotations

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.unique.collaboration import CollaborationManager

_manager: CollaborationManager | None = None


def _get_manager() -> CollaborationManager:
    global _manager
    if _manager is None:
        _manager = CollaborationManager()
    return _manager


async def collab_create_session(session_id: str, file_path: str) -> str:
    mgr = _get_manager()
    try:
        mgr.create_session(session_id, file_path)
        return f"Session '{session_id}' created for file '{file_path}'."
    except Exception as e:
        logger.error("Collab create session failed: {}", e)
        return f"[error] {e}"


async def collab_list_sessions() -> str:
    mgr = _get_manager()
    sessions = mgr.list_sessions()
    if not sessions:
        return "[info] No active sessions."
    lines = [f"Active sessions ({len(sessions)}):"]
    for s in sessions:
        lines.append(f"  - {s['session_id']} ({s['file_path']}) — {s['users']} users, v{s['version']}")
    return "\n".join(lines)


async def collab_join_session(session_id: str, user_id: str, user_name: str) -> str:
    mgr = _get_manager()
    session = mgr.get_session(session_id)
    if not session:
        return f"[error] Session '{session_id}' not found."
    session.add_user(user_id, user_name)
    return f"User '{user_name}' ({user_id}) joined session '{session_id}'."


async def collab_leave_session(session_id: str, user_id: str) -> str:
    mgr = _get_manager()
    session = mgr.get_session(session_id)
    if not session:
        return f"[error] Session '{session_id}' not found."
    session.remove_user(user_id)
    return f"User '{user_id}' left session '{session_id}'."


async def collab_apply_change(session_id: str, file: str, start_line: int, start_col: int, end_line: int, end_col: int, old_text: str, new_text: str) -> str:
    mgr = _get_manager()
    session = mgr.get_session(session_id)
    if not session:
        return f"[error] Session '{session_id}' not found."
    from raven.unique.collaboration import TextChange
    change = TextChange(
        user_id="system",
        file=file,
        start_line=start_line,
        start_col=start_col,
        end_line=end_line,
        end_col=end_col,
        old_text=old_text,
        new_text=new_text,
    )
    ok = session.apply_change(change)
    if ok:
        return f"Change applied (v{session.document.version})."
    return "[error] Change could not be applied."


async def collab_add_comment(session_id: str, user_id: str, file: str, line: int, text: str) -> str:
    mgr = _get_manager()
    session = mgr.get_session(session_id)
    if not session:
        return f"[error] Session '{session_id}' not found."
    comment = session.add_comment(user_id, file, line, text)
    return f"Comment added (id: {comment.id})."


async def collab_session_state(session_id: str) -> str:
    mgr = _get_manager()
    session = mgr.get_session(session_id)
    if not session:
        return f"[error] Session '{session_id}' not found."
    state = session.get_state()
    content_preview = session.document.content[:200].replace("\n", "\\n")
    return (
        f"Session: {state['session_id']}\n"
        f"File: {state['file_path']}\n"
        f"Version: {state['version']}\n"
        f"Users: {state['connected_users']}/{state['users']}\n"
        f"Changes: {state['changes']}\n"
        f"Comments: {state['comments']}\n"
        f"CRDT: {'enabled' if state['crdt_enabled'] else 'disabled'}\n"
        f"Content preview: {content_preview}"
    )


def register_collaboration_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="collab_create_session",
        description="Create a new collaboration session for real-time co-editing",
        parameters={
            "session_id": {"type": "string", "description": "Unique session identifier", "required": True},
            "file_path": {"type": "string", "description": "File path being edited", "required": True},
        },
        handler=collab_create_session,
        category="collaboration",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="collab_list_sessions",
        description="List all active collaboration sessions",
        parameters={},
        handler=collab_list_sessions,
        category="collaboration",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="collab_join_session",
        description="Join a collaboration session",
        parameters={
            "session_id": {"type": "string", "description": "Session identifier", "required": True},
            "user_id": {"type": "string", "description": "User ID", "required": True},
            "user_name": {"type": "string", "description": "Display name", "required": True},
        },
        handler=collab_join_session,
        category="collaboration",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="collab_leave_session",
        description="Leave a collaboration session",
        parameters={
            "session_id": {"type": "string", "description": "Session identifier", "required": True},
            "user_id": {"type": "string", "description": "User ID", "required": True},
        },
        handler=collab_leave_session,
        category="collaboration",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="collab_apply_change",
        description="Apply a text change to a collaboration session document",
        parameters={
            "session_id": {"type": "string", "description": "Session identifier", "required": True},
            "file": {"type": "string", "description": "File path", "required": True},
            "start_line": {"type": "integer", "description": "Start line", "required": True},
            "start_col": {"type": "integer", "description": "Start column", "required": True},
            "end_line": {"type": "integer", "description": "End line", "required": True},
            "end_col": {"type": "integer", "description": "End column", "required": True},
            "old_text": {"type": "string", "description": "Text being replaced", "required": True},
            "new_text": {"type": "string", "description": "New text", "required": True},
        },
        handler=collab_apply_change,
        category="collaboration",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="collab_add_comment",
        description="Add a review comment on a specific line in a collaboration session",
        parameters={
            "session_id": {"type": "string", "description": "Session identifier", "required": True},
            "user_id": {"type": "string", "description": "User ID", "required": True},
            "file": {"type": "string", "description": "File path", "required": True},
            "line": {"type": "integer", "description": "Line number", "required": True},
            "text": {"type": "string", "description": "Comment text", "required": True},
        },
        handler=collab_add_comment,
        category="collaboration",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="collab_session_state",
        description="Get the current state of a collaboration session",
        parameters={
            "session_id": {"type": "string", "description": "Session identifier", "required": True},
        },
        handler=collab_session_state,
        category="collaboration",
        timeout=10,
    ))

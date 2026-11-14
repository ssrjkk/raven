from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

try:
    from y_py import YDoc

    HAS_YPY = True
except ImportError:
    HAS_YPY = False
    logger.warning("y-py not available, using fallback CRDT implementation")

_MAX_CHANGE_HISTORY = 500


@dataclass
class CursorPosition:
    user_id: str
    file: str
    line: int
    column: int
    timestamp: float = 0.0


@dataclass
class TextChange:
    user_id: str
    file: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    old_text: str
    new_text: str
    timestamp: float = 0.0
    version: int = 0


@dataclass
class Comment:
    id: str
    user_id: str
    file: str
    line: int
    text: str
    timestamp: float = 0.0
    resolved: bool = False
    replies: list[Comment] = field(default_factory=list)


@dataclass
class DocumentState:
    content: str
    version: int = 0
    changes: deque[TextChange] = field(default_factory=lambda: deque(maxlen=_MAX_CHANGE_HISTORY))
    change_count: int = 0


@dataclass
class SessionNotification:
    kind: str
    session_id: str
    payload: dict[str, Any]
    timestamp: float = 0.0


@dataclass
class UserSessionInfo:
    user_id: str
    user_name: str
    connected: bool = False
    joined_at: float = 0.0


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[Any]] = defaultdict(set)
        self._user_connections: dict[str, set[tuple[str, Any]]] = defaultdict(set)

    async def connect(self, session_id: str, user_id: str, websocket: Any) -> None:
        self._connections[session_id].add(websocket)
        self._user_connections[user_id].add((session_id, websocket))
        await self._broadcast_json(
            session_id,
            {"kind": "user_connected", "user_id": user_id, "session_id": session_id},
            exclude=websocket,
        )

    async def disconnect(self, session_id: str, user_id: str, websocket: Any) -> None:
        self._connections[session_id].discard(websocket)
        self._user_connections[user_id].discard((session_id, websocket))
        if not self._connections[session_id]:
            del self._connections[session_id]
        if not self._user_connections[user_id]:
            del self._user_connections[user_id]
        await self._broadcast_json(
            session_id,
            {"kind": "user_disconnected", "user_id": user_id, "session_id": session_id},
        )

    async def broadcast(self, session_id: str, message: str, exclude: Any = None) -> None:
        for ws in list(self._connections.get(session_id, set())):
            if ws is exclude:
                continue
            try:
                await ws.send_text(message)
            except Exception as exc:
                logger.debug("WebSocket send failed: {}", exc)
                self._connections[session_id].discard(ws)

    async def broadcast_json(self, session_id: str, data: dict[str, Any], exclude: Any = None) -> None:
        await self.broadcast(session_id, json.dumps(data), exclude=exclude)

    async def _broadcast_json(self, session_id: str, data: dict[str, Any], exclude: Any = None) -> None:
        await self.broadcast_json(session_id, data, exclude=exclude)

    async def broadcast_to_user(self, user_id: str, data: dict[str, Any]) -> None:
        for session_id, ws in list(self._user_connections.get(user_id, set())):
            try:
                await ws.send_text(json.dumps(data))
            except Exception as exc:
                logger.debug("WebSocket send to user {} failed: {}", user_id, exc)
                self._user_connections[user_id].discard((session_id, ws))

    def connection_count(self, session_id: str) -> int:
        return len(self._connections.get(session_id, set()))

    def active_sessions(self) -> list[str]:
        return list(self._connections.keys())

    async def disconnect_all(self, session_id: str) -> None:
        for ws in list(self._connections.get(session_id, set())):
            try:
                await ws.close()
            except Exception as exc:
                logger.debug("Failed to close WS in session {}: {}", session_id, exc)
        self._connections.pop(session_id, None)


class CollaborationSession:
    def __init__(self, session_id: str, file_path: str) -> None:
        self.session_id = session_id
        self.file_path = file_path
        self.document = DocumentState(content="")
        self.users: dict[str, str] = {}
        self.cursors: dict[str, CursorPosition] = {}
        self.comments: list[Comment] = []
        self.user_info: dict[str, UserSessionInfo] = {}
        self._notifications: asyncio.Queue[SessionNotification] = asyncio.Queue()

        if HAS_YPY:
            self._ydoc = YDoc()
            self._ytext = self._ydoc.get_text(file_path)
            self._ytext.observe(self._on_ytext_change)
            self._version_vector: bytes | None = None
            logger.debug("YDoc initialized for session {}", session_id)
        else:
            self._ydoc = None
            self._ytext = None

    def _on_ytext_change(self, delta: list[dict[str, Any]], _remote: bool) -> None:
        logger.trace("YText change in session {}: {}", self.session_id, delta)

    def add_user(self, user_id: str, user_name: str) -> None:
        self.users[user_id] = user_name
        if user_id not in self.user_info:
            self.user_info[user_id] = UserSessionInfo(
                user_id=user_id,
                user_name=user_name,
                joined_at=time.time(),
                connected=True,
            )
        else:
            self.user_info[user_id].connected = True

    def remove_user(self, user_id: str) -> None:
        self.users.pop(user_id, None)
        self.cursors.pop(user_id, None)
        if user_id in self.user_info:
            self.user_info[user_id].connected = False

    def update_cursor(self, user_id: str, file: str, line: int, column: int) -> CursorPosition:
        pos = CursorPosition(
            user_id=user_id,
            file=file,
            line=line,
            column=column,
            timestamp=time.time(),
        )
        self.cursors[user_id] = pos
        return pos

    def apply_change(self, change: TextChange) -> bool:
        change.timestamp = time.time()
        change.version = self.document.version + 1

        if HAS_YPY and self._ytext is not None:
            return self._apply_change_crdt(change)
        return self._apply_change_fallback(change)

    def _change_range(self, content: str, change: TextChange) -> tuple[int, int] | None:
        """Resolve a line/column change into offsets into `content`, or None if it is not a range.

        Both apply paths go through here. They used to each check the bounds and disagree about a
        reversed range: the y-py path inserted at the start without deleting, the fallback refused,
        so the same change from the same client was applied on one install and dropped on another.
        """
        lines = content.split("\n")
        if not 0 <= change.start_line < len(lines):
            return None
        if not 0 <= change.end_line < len(lines):
            return None
        start = self._pos_to_offset(lines, change.start_line, change.start_col)
        end = self._pos_to_offset(lines, change.end_line, change.end_col)
        if end < start:
            return None
        return start, end

    def _apply_change_crdt(self, change: TextChange) -> bool:
        try:
            rng = self._change_range(str(self._ytext), change)
            if rng is None:
                return False
            start, end = rng

            if end > start:
                self._ytext.delete(start, end - start)
            if change.new_text:
                self._ytext.insert(start, change.new_text)

            self.document.content = str(self._ytext)
            self.document.version += 1
            self.document.changes.append(change)
            self.document.change_count += 1
            return True
        except Exception as exc:
            logger.error("CRDT apply_change failed: {}", exc)
            return self._apply_change_fallback(change)

    def _apply_change_fallback(self, change: TextChange) -> bool:
        content = self.document.content
        rng = self._change_range(content, change)
        if rng is None:
            return False
        start, end = rng

        # One splice. The branch this replaces rebuilt the line list by hand and then popped as many
        # lines as the replaced range spanned, which deleted the lines it had just inserted: `X\nY`
        # over lines 1-2 of "a\nb\nc\nd" came back as "a\nbX\nd" -- a client applying the same change
        # itself would have diverged from the document the server holds.
        self.document.content = content[:start] + change.new_text + content[end:]

        self.document.version += 1
        self.document.changes.append(change)
        self.document.change_count += 1
        return True

    def _pos_to_offset(self, lines: list[str], line: int, col: int) -> int:
        offset = 0
        for i in range(line):
            offset += len(lines[i]) + 1
        return offset + col

    def get_crdt_state_vector(self) -> bytes | None:
        if HAS_YPY and self._ydoc is not None:
            return self._ydoc.encode_state_vector()  # type: ignore[no-any-return]
        return None

    def apply_crdt_update(self, update: bytes) -> bool:
        if HAS_YPY and self._ydoc is not None:
            try:
                self._ydoc.apply(update)
                self.document.content = str(self._ytext)
                return True
            except Exception as exc:
                logger.error("CRDT apply_update failed: {}", exc)
                return False
        return False

    def encode_crdt_diff(self, state_vector: bytes) -> bytes | None:
        if HAS_YPY and self._ydoc is not None:
            try:
                return self._ydoc.encode_diff(state_vector)  # type: ignore[no-any-return]
            except Exception as exc:
                logger.error("CRDT encode_diff failed: {}", exc)
                return None
        return None

    def get_crdt_content(self) -> str:
        if HAS_YPY and self._ytext is not None:
            return str(self._ytext)
        return self.document.content

    def set_crdt_content(self, content: str) -> None:
        if HAS_YPY and self._ytext is not None:
            current = str(self._ytext)
            if current:
                self._ytext.delete(0, len(current))
            if content:
                self._ytext.insert(0, content)
        self.document.content = content

    def _find_comment(self, comment_id: str) -> Comment | None:
        for comment in self.comments:
            if comment.id == comment_id:
                return comment
            for reply in comment.replies:
                if reply.id == comment_id:
                    return reply
        return None

    def add_comment(self, user_id: str, file: str, line: int, text: str) -> Comment:
        comment = Comment(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            file=file,
            line=line,
            text=text,
            timestamp=time.time(),
        )
        self.comments.append(comment)
        return comment

    def add_reply(self, parent_id: str, user_id: str, text: str) -> Comment | None:
        parent = self._find_comment(parent_id)
        if not parent:
            return None
        reply = Comment(
            id=uuid.uuid4().hex[:12],
            user_id=user_id,
            file=parent.file,
            line=parent.line,
            text=text,
            timestamp=time.time(),
        )
        parent.replies.append(reply)
        return reply

    def resolve_comment(self, comment_id: str) -> bool:
        comment = self._find_comment(comment_id)
        if not comment:
            return False
        comment.resolved = True
        return True

    def get_cursors(self) -> list[CursorPosition]:
        return list(self.cursors.values())

    def get_comments(self, resolved: bool | None = None) -> list[Comment]:
        if resolved is None:
            return self.comments
        return [c for c in self.comments if c.resolved == resolved]

    def get_user_list(self) -> list[dict[str, str]]:
        return [{"id": uid, "name": name} for uid, name in self.users.items()]

    def get_user_info_list(self) -> list[dict[str, Any]]:
        return [
            {
                "user_id": info.user_id,
                "user_name": info.user_name,
                "connected": info.connected,
                "joined_at": info.joined_at,
            }
            for info in self.user_info.values()
        ]

    def get_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "file_path": self.file_path,
            "version": self.document.version,
            "users": len(self.users),
            "connected_users": sum(1 for u in self.user_info.values() if u.connected),
            "changes": self.document.change_count,
            "comments": len(self.comments),
            "crdt_enabled": HAS_YPY and self._ydoc is not None,
        }

    async def poll_notifications(self) -> SessionNotification | None:
        try:
            return await asyncio.wait_for(self._notifications.get(), timeout=0.1)
        except TimeoutError:
            return None

    async def notify(self, notification: SessionNotification) -> None:
        await self._notifications.put(notification)


class CollaborationManager:
    def __init__(self) -> None:
        self._sessions: dict[str, CollaborationSession] = {}

    def create_session(self, session_id: str, file_path: str) -> CollaborationSession:
        session = CollaborationSession(session_id, file_path)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> CollaborationSession | None:
        return self._sessions.get(session_id)

    def remove_session(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[dict[str, Any]]:
        return [s.get_state() for s in self._sessions.values()]

    def list_active_users(self) -> list[dict[str, str]]:
        users: dict[str, str] = {}
        for session in self._sessions.values():
            for uid, name in session.users.items():
                users[uid] = name  # noqa: PERF403
        return [{"id": uid, "name": name} for uid, name in users.items()]

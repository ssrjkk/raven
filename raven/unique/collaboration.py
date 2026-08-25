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

    def _apply_change_crdt(self, change: TextChange) -> bool:
        try:
            current = str(self._ytext)
            lines = current.split("\n")
            if change.start_line < 0 or change.start_line >= len(lines):
                return False
            if change.end_line < 0 or change.end_line >= len(lines):
                return False

            start_offset = self._pos_to_offset(lines, change.start_line, change.start_col)
            end_offset = self._pos_to_offset(lines, change.end_line, change.end_col)

            if end_offset > start_offset:
                self._ytext.delete(start_offset, end_offset - start_offset)
            if change.new_text:
                self._ytext.insert(start_offset, change.new_text)

            self.document.content = str(self._ytext)
            self.document.version += 1
            self.document.changes.append(change)
            self.document.change_count += 1
            return True
        except Exception as exc:
            logger.error("CRDT apply_change failed: {}", exc)
            return self._apply_change_fallback(change)

    def _apply_change_fallback(self, change: TextChange) -> bool:
        lines = self.document.content.split("\n")
        if change.start_line < 0 or change.start_line >= len(lines):
            return False
        if change.end_line < 0 or change.end_line >= len(lines):
            return False

        if change.start_line == change.end_line:
            line = lines[change.start_line]
            lines[change.start_line] = line[: change.start_col] + change.new_text + line[change.end_col :]
        else:
            start_part = lines[change.start_line][: change.start_col]
            end_part = lines[change.end_line][change.end_col :]
            new_lines = change.new_text.split("\n")

            lines[change.start_line] = start_part + new_lines[0]
            for i in range(1, len(new_lines) - 1):
                lines.insert(change.start_line + i, new_lines[i])
            if len(new_lines) > 1:
                lines[change.start_line + len(new_lines) - 1] = new_lines[-1] + end_part

            for _ in range(change.end_line - change.start_line):
                if change.start_line + 1 < len(lines):
                    lines.pop(change.start_line + 1)

        self.document.content = "\n".join(lines)
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


class RealTimeCollaboration:
    def __init__(self) -> None:
        self._manager = CollaborationManager()
        self._ws_manager = WebSocketManager()

    def get_manager(self) -> CollaborationManager:
        return self._manager

    def get_ws_manager(self) -> WebSocketManager:
        return self._ws_manager

    async def edit(self, user_id: str, changes: list[TextChange]) -> bool:
        session_id = self._find_user_session(user_id)
        if not session_id:
            logger.warning("Edit failed: no active session for user {}", user_id)
            return False
        session = self._manager.get_session(session_id)
        if not session:
            return False
        all_ok = True
        for change in changes:
            change.user_id = user_id
            ok = session.apply_change(change)
            if ok:
                await self._ws_manager.broadcast_json(
                    session_id,
                    {
                        "kind": "text_change",
                        "change": {
                            "user_id": change.user_id,
                            "file": change.file,
                            "start_line": change.start_line,
                            "start_col": change.start_col,
                            "end_line": change.end_line,
                            "end_col": change.end_col,
                            "old_text": change.old_text,
                            "new_text": change.new_text,
                            "version": change.version,
                        },
                    },
                )
            else:
                all_ok = False
        return all_ok

    def _find_user_session(self, user_id: str) -> str | None:
        for sid, session in self._manager._sessions.items():
            if user_id in session.users:
                return sid
        return None

    def create_session(self, session_id: str, file_path: str) -> CollaborationSession:
        session = self._manager.create_session(session_id, file_path)
        logger.info("Session created: {} (file: {})", session_id, file_path)
        return session

    async def join_session(self, session_id: str, user_id: str, user_name: str) -> CollaborationSession | None:
        session = self._manager.get_session(session_id)
        if not session:
            logger.warning("Join failed: session {} not found", session_id)
            return None
        session.add_user(user_id, user_name)
        await self._ws_manager.broadcast_json(
            session_id,
            {"kind": "user_joined", "user_id": user_id, "user_name": user_name, "session_id": session_id},
        )
        logger.info("User {} joined session {}", user_id, session_id)
        return session

    async def leave_session(self, session_id: str, user_id: str) -> bool:
        session = self._manager.get_session(session_id)
        if not session:
            return False
        session.remove_user(user_id)
        await self._ws_manager.broadcast_json(
            session_id,
            {"kind": "user_left", "user_id": user_id, "session_id": session_id},
        )
        logger.info("User {} left session {}", user_id, session_id)
        return True

    def get_active_sessions(self) -> list[dict[str, Any]]:
        return self._manager.list_sessions()

    async def apply_change(self, session_id: str, change: TextChange) -> bool:
        session = self._manager.get_session(session_id)
        if not session:
            return False
        ok = session.apply_change(change)
        if ok:
            await self._ws_manager.broadcast_json(
                session_id,
                {
                    "kind": "text_change",
                    "change": {
                        "user_id": change.user_id,
                        "file": change.file,
                        "start_line": change.start_line,
                        "start_col": change.start_col,
                        "end_line": change.end_line,
                        "end_col": change.end_col,
                        "old_text": change.old_text,
                        "new_text": change.new_text,
                        "version": change.version,
                    },
                },
            )
        return ok

    async def update_cursor(
        self, session_id: str, user_id: str, file: str, line: int, column: int
    ) -> CursorPosition | None:
        session = self._manager.get_session(session_id)
        if not session:
            return None
        pos = session.update_cursor(user_id, file, line, column)
        await self._ws_manager.broadcast_json(
            session_id,
            {
                "kind": "cursor_update",
                "cursor": {
                    "user_id": user_id,
                    "file": file,
                    "line": line,
                    "column": column,
                    "timestamp": pos.timestamp,
                },
            },
        )
        return pos

    async def add_comment(self, session_id: str, user_id: str, file: str, line: int, text: str) -> Comment | None:
        session = self._manager.get_session(session_id)
        if not session:
            return None
        comment = session.add_comment(user_id, file, line, text)
        await self._ws_manager.broadcast_json(
            session_id,
            {
                "kind": "comment_added",
                "comment": {
                    "id": comment.id,
                    "user_id": user_id,
                    "file": file,
                    "line": line,
                    "text": text,
                    "timestamp": comment.timestamp,
                },
            },
        )
        return comment

    async def add_reply(self, session_id: str, parent_id: str, user_id: str, text: str) -> Comment | None:
        session = self._manager.get_session(session_id)
        if not session:
            return None
        reply = session.add_reply(parent_id, user_id, text)
        if reply:
            await self._ws_manager.broadcast_json(
                session_id,
                {
                    "kind": "reply_added",
                    "reply": {
                        "id": reply.id,
                        "parent_id": parent_id,
                        "user_id": user_id,
                        "text": text,
                        "timestamp": reply.timestamp,
                    },
                },
            )
        return reply

    async def resolve_comment(self, session_id: str, comment_id: str) -> bool:
        session = self._manager.get_session(session_id)
        if not session:
            return False
        ok = session.resolve_comment(comment_id)
        if ok:
            await self._ws_manager.broadcast_json(
                session_id,
                {"kind": "comment_resolved", "comment_id": comment_id},
            )
        return ok

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        session = self._manager.get_session(session_id)
        if not session:
            return None
        return {
            **session.get_state(),
            "cursors": [
                {"user_id": c.user_id, "file": c.file, "line": c.line, "column": c.column}
                for c in session.get_cursors()
            ],
            "comments": [
                {
                    "id": c.id,
                    "user_id": c.user_id,
                    "text": c.text[:80],
                    "resolved": c.resolved,
                    "replies": len(c.replies),
                }
                for c in session.get_comments()
            ],
            "users": session.get_user_list(),
            "user_info": session.get_user_info_list(),
            "connections": self._ws_manager.connection_count(session_id),
        }

    def sync_crdt_state(self, session_id: str, target_session_id: str | None = None) -> bytes | None:
        session = self._manager.get_session(session_id)
        if not session:
            return None
        sv = session.get_crdt_state_vector()
        if sv is None:
            return None
        if target_session_id:
            target = self._manager.get_session(target_session_id)
            if target and target.get_crdt_state_vector():
                diff = session.encode_crdt_diff(sv)
                if diff:
                    target.apply_crdt_update(diff)
        return session.encode_crdt_diff(b"")

    def remove_session(self, session_id: str) -> bool:
        return self._manager.remove_session(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._manager.list_sessions()

    def get_session(self, session_id: str) -> CollaborationSession | None:
        return self._manager.get_session(session_id)

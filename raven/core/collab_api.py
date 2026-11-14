from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field

from raven.core.api_errors import internal_error
from raven.unique.collaboration import CollaborationManager, TextChange, WebSocketManager


async def _ws_identity(websocket: WebSocket) -> str | None:
    """Resolve the socket's caller from `?token=`, the credential the HTTP gate accepts.

    The identity must come from the token: a `user_id` claimed in the first message is whatever
    the caller says it is, and it ends up stamped on every change and cursor it broadcasts.
    """
    from raven.core.auth.auth_handler import auth_handler
    from raven.core.config import settings

    token = websocket.query_params.get("token", "")
    if not token:
        return None
    secret = settings.web_secret_key.get_secret_value()
    if secret and hmac.compare_digest(token, secret):
        return "admin"
    payload = await auth_handler.decode_token(token)
    if payload is None:
        return None
    return str(payload["sub"])


_manager: CollaborationManager | None = None
_ws_manager: WebSocketManager | None = None


def get_ws_manager() -> WebSocketManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager


def get_manager() -> CollaborationManager:
    """The one session registry, named so the agent tool reads and writes the same sessions the
    console does. `raven/tools/collaboration.py` kept a private instance of its own, so a session an
    agent created was never listed by `/api/collab/sessions` and a session the console opened was
    `Session not found` to the tool."""
    global _manager
    if _manager is None:
        _manager = CollaborationManager()
    return _manager


def _change_frame(change: TextChange, version: int) -> dict[str, Any]:
    """The one shape a live editor is told about an edit in.

    Three senders used to agree on nothing else: the socket handler broadcast this flat frame, the REST
    endpoint broadcast nothing, and `RealTimeCollaboration` broadcast a nested `text_change` from a
    registry no caller could reach. A client therefore had to guess which of the three paths produced an
    edit -- or, as the console did, ignore the socket entirely.
    """
    return {
        "kind": "change",
        "user_id": change.user_id,
        "file": change.file,
        "start_line": change.start_line,
        "start_col": change.start_col,
        "end_line": change.end_line,
        "end_col": change.end_col,
        "old_text": change.old_text,
        "new_text": change.new_text,
        "version": version,
    }


def _comment_body(comment: Any) -> dict[str, Any]:
    """One comment, in the one shape every reader of a session sees.

    The REST snapshot used to leave `file` out while the announcement carried it, so a client had to
    keep two comment models for the same object.
    """
    return {
        "id": comment.id,
        "user_id": comment.user_id,
        "file": comment.file,
        "line": comment.line,
        "text": comment.text,
        "resolved": comment.resolved,
    }


def _comment_frame(comment: Any) -> dict[str, Any]:
    return {**_comment_body(comment), "kind": "comment_added"}


def _presence_frame(kind: str, session_id: str, user_id: str, user_name: str = "") -> dict[str, Any]:
    """Who joined or left, in the shape `WebSocketManager` already uses for a socket.

    The REST join and leave were silent, so a session that one user opened over HTTP and another was
    watching over a socket kept the watcher's user list frozen until the page reloaded.
    """
    frame: dict[str, Any] = {"kind": kind, "user_id": user_id, "session_id": session_id}
    if user_name:
        frame["user_name"] = user_name
    return frame


class CreateSessionRequest(BaseModel):
    session_id: str = Field(..., max_length=100)
    file_path: str = Field(..., max_length=500)


class JoinSessionRequest(BaseModel):
    session_id: str = Field(..., max_length=100)
    user_id: str = Field(..., max_length=100)
    user_name: str = Field(..., max_length=100)


class LeaveSessionRequest(BaseModel):
    session_id: str = Field(..., max_length=100)
    user_id: str = Field(..., max_length=100)


class ApplyChangeRequest(BaseModel):
    session_id: str = Field(..., max_length=100)
    user_id: str = Field(default="api", max_length=100)
    file: str = Field(..., max_length=500)
    start_line: int = Field(..., ge=0)
    start_col: int = Field(..., ge=0)
    end_line: int = Field(..., ge=0)
    end_col: int = Field(..., ge=0)
    old_text: str = Field(..., max_length=50000)
    new_text: str = Field(..., max_length=50000)


class AddCommentRequest(BaseModel):
    session_id: str = Field(..., max_length=100)
    user_id: str = Field(..., max_length=100)
    file: str = Field(..., max_length=500)
    line: int = Field(..., ge=0)
    text: str = Field(..., max_length=10000)


def create_collab_router() -> APIRouter:
    router = APIRouter(prefix="/api/collab", tags=["collaboration"])

    @router.post("/sessions")
    async def create_session(req: CreateSessionRequest):
        mgr = get_manager()
        try:
            session = mgr.create_session(req.session_id, req.file_path)
            return {"session_id": session.session_id, "file_path": session.file_path}
        except Exception as e:
            raise internal_error(e) from e

    @router.get("/sessions")
    async def list_sessions():
        mgr = get_manager()
        return {"sessions": mgr.list_sessions()}

    @router.post("/sessions/{session_id}/join")
    async def join_session(session_id: str, req: JoinSessionRequest):
        mgr = get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        session.add_user(req.user_id, req.user_name)
        await get_ws_manager().broadcast_json(
            session_id, _presence_frame("user_connected", session_id, req.user_id, req.user_name)
        )
        return {"success": True, "session_id": session_id, "user_id": req.user_id}

    @router.post("/sessions/{session_id}/leave")
    async def leave_session(session_id: str, req: LeaveSessionRequest):
        mgr = get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        session.remove_user(req.user_id)
        await get_ws_manager().broadcast_json(session_id, _presence_frame("user_disconnected", session_id, req.user_id))
        return {"success": True}

    @router.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        mgr = get_manager()
        ws_mgr = get_ws_manager()
        await ws_mgr.disconnect_all(session_id)
        if not mgr.remove_session(session_id):
            raise HTTPException(404, f"Session '{session_id}' not found")
        return {"success": True}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        mgr = get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        return {
            **session.get_state(),
            "content": session.document.content,
            "cursors": [
                {"user_id": c.user_id, "file": c.file, "line": c.line, "column": c.column}
                for c in session.get_cursors()
            ],
            "comments": [_comment_body(c) for c in session.get_comments()],
            "users": session.get_user_list(),
        }

    @router.post("/sessions/{session_id}/changes")
    async def apply_change(session_id: str, req: ApplyChangeRequest):
        mgr = get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        change = TextChange(
            user_id=req.user_id,
            file=req.file,
            start_line=req.start_line,
            start_col=req.start_col,
            end_line=req.end_line,
            end_col=req.end_col,
            old_text=req.old_text,
            new_text=req.new_text,
        )
        ok = session.apply_change(change)
        if not ok:
            raise HTTPException(400, "Change could not be applied")
        # An edit made over HTTP is an edit every live editor of that session has to be told about;
        # this call was missing, so the REST path changed the document silently and only the socket
        # path notified.
        await get_ws_manager().broadcast_json(session_id, _change_frame(change, session.document.version))
        return {"version": session.document.version, "success": True}

    @router.post("/sessions/{session_id}/comments")
    async def add_comment(session_id: str, req: AddCommentRequest):
        mgr = get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        comment = session.add_comment(req.user_id, req.file, req.line, req.text)
        await get_ws_manager().broadcast_json(session_id, _comment_frame(comment))
        return {"id": comment.id, "success": True}

    @router.get("/sessions/{session_id}/content")
    async def get_content(session_id: str):
        mgr = get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        return {"content": session.document.content, "version": session.document.version}

    @router.websocket("/sessions/{session_id}/ws")
    async def collab_websocket(session_id: str, websocket: WebSocket):
        user_id = await _ws_identity(websocket)
        if user_id is None:
            await websocket.accept()
            await websocket.close(code=1008, reason="Authentication required")
            return
        await websocket.accept()
        wsm = get_ws_manager()
        await wsm.connect(session_id, user_id, websocket)
        mgr = get_manager()
        session = mgr.get_session(session_id)
        if session:
            # Everything the REST snapshot of this session answers with, so a socket that joins late
            # starts from the same document, reader list and review state as a page reload would.
            await websocket.send_json(
                {
                    "kind": "state",
                    "content": session.document.content,
                    "version": session.document.version,
                    "users": session.get_user_list(),
                    "comments": [_comment_body(c) for c in session.get_comments()],
                    "cursors": [
                        {"user_id": c.user_id, "file": c.file, "line": c.line, "column": c.column}
                        for c in session.get_cursors()
                    ],
                }
            )
        try:
            while True:
                data = await websocket.receive_json()
                kind = data.get("kind", "")
                if kind == "change":
                    if session is None:
                        # No session was mounted when this socket connected. The frame used to be read,
                        # dropped and answered with silence, so the editor waited for a change that was
                        # never going to arrive.
                        await websocket.send_json(
                            {"kind": "error", "content": f"Session '{session_id}' is not open on this gateway"}
                        )
                        continue
                    change = TextChange(
                        user_id=user_id,
                        file=data.get("file", ""),
                        start_line=data.get("start_line", 0),
                        start_col=data.get("start_col", 0),
                        end_line=data.get("end_line", 0),
                        end_col=data.get("end_col", 0),
                        old_text=data.get("old_text", ""),
                        new_text=data.get("new_text", ""),
                    )
                    ok = session.apply_change(change)
                    if ok:
                        await wsm.broadcast_json(
                            session_id, _change_frame(change, session.document.version), exclude=websocket
                        )
                        await websocket.send_json({"kind": "ack", "version": session.document.version})
                    else:
                        await websocket.send_json(
                            {"kind": "error", "content": f"Change could not be applied to '{session_id}'"}
                        )
                elif kind == "cursor":
                    await wsm.broadcast_json(
                        session_id,
                        {
                            "kind": "cursor",
                            "user_id": user_id,
                            "file": data.get("file", ""),
                            "line": data.get("line", 0),
                            "column": data.get("column", 0),
                        },
                        exclude=websocket,
                    )
                elif kind == "ping":
                    await websocket.send_json({"kind": "pong"})
                else:
                    await websocket.send_json({"kind": "error", "content": f"Unknown frame kind '{kind!r}'"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("WebSocket handler error: {}", e)
        finally:
            wsm = get_ws_manager()
            await wsm.disconnect(session_id, user_id, websocket)

    return router

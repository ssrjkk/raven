from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from raven.unique.collaboration import CollaborationManager, TextChange, WebSocketManager

_manager: CollaborationManager | None = None
_ws_manager: WebSocketManager | None = None


def _get_ws_manager() -> WebSocketManager:
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager


def _get_manager() -> CollaborationManager:
    global _manager
    if _manager is None:
        _manager = CollaborationManager()
    return _manager


class CreateSessionRequest(BaseModel):
    session_id: str
    file_path: str


class JoinSessionRequest(BaseModel):
    session_id: str
    user_id: str
    user_name: str


class LeaveSessionRequest(BaseModel):
    session_id: str
    user_id: str


class ApplyChangeRequest(BaseModel):
    session_id: str
    user_id: str = "api"
    file: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    old_text: str
    new_text: str


class AddCommentRequest(BaseModel):
    session_id: str
    user_id: str
    file: str
    line: int
    text: str


def create_collab_router() -> APIRouter:
    router = APIRouter(prefix="/api/collab", tags=["collaboration"])

    @router.post("/sessions")
    async def create_session(req: CreateSessionRequest):
        mgr = _get_manager()
        try:
            session = mgr.create_session(req.session_id, req.file_path)
            return {"session_id": session.session_id, "file_path": session.file_path}
        except Exception as e:
            raise HTTPException(500, str(e)) from e

    @router.get("/sessions")
    async def list_sessions():
        mgr = _get_manager()
        return {"sessions": mgr.list_sessions()}

    @router.post("/sessions/{session_id}/join")
    async def join_session(session_id: str, req: JoinSessionRequest):
        mgr = _get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        session.add_user(req.user_id, req.user_name)
        return {"success": True, "session_id": session_id, "user_id": req.user_id}

    @router.post("/sessions/{session_id}/leave")
    async def leave_session(session_id: str, req: LeaveSessionRequest):
        mgr = _get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        session.remove_user(req.user_id)
        return {"success": True}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        mgr = _get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        return {
            **session.get_state(),
            "content": session.document.content,
            "cursors": [{"user_id": c.user_id, "file": c.file, "line": c.line, "column": c.column} for c in session.get_cursors()],
            "comments": [{"id": c.id, "user_id": c.user_id, "text": c.text, "resolved": c.resolved, "line": c.line} for c in session.get_comments()],
            "users": session.get_user_list(),
        }

    @router.post("/sessions/{session_id}/changes")
    async def apply_change(session_id: str, req: ApplyChangeRequest):
        mgr = _get_manager()
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
        return {"version": session.document.version, "success": True}

    @router.post("/sessions/{session_id}/comments")
    async def add_comment(session_id: str, req: AddCommentRequest):
        mgr = _get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        comment = session.add_comment(req.user_id, req.file, req.line, req.text)
        return {"id": comment.id, "success": True}

    @router.get("/sessions/{session_id}/content")
    async def get_content(session_id: str):
        mgr = _get_manager()
        session = mgr.get_session(session_id)
        if not session:
            raise HTTPException(404, f"Session '{session_id}' not found")
        return {"content": session.document.content, "version": session.document.version}

    @router.websocket("/sessions/{session_id}/ws")
    async def collab_websocket(session_id: str, websocket: WebSocket):
        await websocket.accept()
        user_id = "anon"
        try:
            msg = await websocket.receive_json()
            if msg.get("kind") == "auth" and msg.get("user_id"):
                user_id = msg["user_id"]
            wsm = _get_ws_manager()
            await wsm.connect(session_id, user_id, websocket)
            mgr = _get_manager()
            session = mgr.get_session(session_id)
            if session:
                await websocket.send_json({
                    "kind": "state",
                    "content": session.document.content,
                    "version": session.document.version,
                    "users": session.get_user_list(),
                })
            while True:
                data = await websocket.receive_json()
                kind = data.get("kind", "")
                if kind == "change" and session:
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
                        await wsm.broadcast_json(session_id, {
                            "kind": "change",
                            "user_id": user_id,
                            "file": change.file,
                            "start_line": change.start_line,
                            "start_col": change.start_col,
                            "end_line": change.end_line,
                            "end_col": change.end_col,
                            "old_text": change.old_text,
                            "new_text": change.new_text,
                            "version": session.document.version,
                        }, exclude=websocket)
                        await websocket.send_json({"kind": "ack", "version": session.document.version})
                elif kind == "cursor":
                    await wsm.broadcast_json(session_id, {
                        "kind": "cursor",
                        "user_id": user_id,
                        "file": data.get("file", ""),
                        "line": data.get("line", 0),
                        "column": data.get("column", 0),
                    }, exclude=websocket)
                elif kind == "ping":
                    await websocket.send_json({"kind": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("WebSocket handler error: {}", e)
        finally:
            wsm = _get_ws_manager()
            await wsm.disconnect(session_id, user_id, websocket)

    return router

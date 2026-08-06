from __future__ import annotations

import os
import re
import sys
import threading
import traceback
from pathlib import Path
from types import FrameType
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from raven.core.security.path_guard import confine_path
from raven.tools.file import _check_no_symlinks_in_path

_SANITIZE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(api[_-]?key|secret|token|password|credential)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.)"),  # JWT tokens
]
_MAX_FILE_SIZE = 512_000  # 500 KB — debug only, not arbitrary file read
_ALLOWED_EXTENSIONS = frozenset({".py", ".pyw"})
_WORKSPACE: Path | None = None


def _get_workspace() -> Path:
    global _WORKSPACE
    if _WORKSPACE is None:
        _WORKSPACE = Path(os.environ.get("RAVEN_WORKSPACE", Path(__file__).parent.parent.parent / "workspace")).resolve()
    return _WORKSPACE


def _confine_path(file_path: str) -> Path:
    return confine_path(file_path, _get_workspace())


def _sanitize_traceback(tb_str: str) -> str:
    for pat in _SANITIZE_PATTERNS:
        tb_str = pat.sub(lambda m: f"{m.group(1).split('=')[0].split(':')[0]}=***", tb_str)
    return tb_str


async def _require_admin(request: Request) -> dict[str, Any]:
    user_role = getattr(request.state, "user_role", None)
    if user_role not in ("admin", "superadmin"):
        raise HTTPException(403, "Debug endpoints require admin role")
    return {"role": user_role}


class BreakpointRequest(BaseModel):
    file: str
    line: int
    enabled: bool = True


class DebugStartRequest(BaseModel):
    file: str
    breakpoints: list[BreakpointRequest] = []


class DebuggerState(BaseModel):
    status: str  # idle | running | paused | stopped | error
    paused_file: str | None = None
    paused_line: int | None = None
    frames: list[dict[str, Any]] = []
    error: str | None = None


_active_debugger: _DebugSession | None = None
_debug_lock = threading.Lock()


def create_debugger_router() -> APIRouter:
    router = APIRouter(prefix="/api/debug", tags=["debug"])

    @router.post("/start")
    async def debug_start(req: DebugStartRequest, _admin: dict[str, Any] = Depends(_require_admin)) -> DebuggerState:
        global _active_debugger
        base = os.path.abspath(str(_get_workspace()))  # noqa: PTH100
        resolved = os.path.abspath(os.path.normpath(os.path.expanduser(req.file)))  # noqa: PTH100, PTH111
        if not resolved.startswith(base):
            raise HTTPException(403, f"Access denied: {req.file}")
        if resolved != base and not resolved.startswith(base + os.sep):
            raise HTTPException(403, f"Access denied: {req.file}")
        file_path = Path(resolved)
        _check_no_symlinks_in_path(file_path, Path(base))
        if not file_path.is_file():
            raise HTTPException(404, f"File not found: {req.file}")
        if file_path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            raise HTTPException(403, f"Only .py files can be debugged, got: {file_path.suffix}")
        if file_path.stat().st_size > _MAX_FILE_SIZE:
            raise HTTPException(400, f"File too large for debugging ({file_path.stat().st_size} > {_MAX_FILE_SIZE} bytes)")
        with _debug_lock:
            if _active_debugger is not None:
                _active_debugger.stop()
                _active_debugger = None
        session = _DebugSession(file_path, req.breakpoints)
        with _debug_lock:
            _active_debugger = session
        session.start()
        return session.get_state()

    @router.post("/stop")
    async def debug_stop(_admin: dict[str, Any] = Depends(_require_admin)) -> DebuggerState:
        global _active_debugger
        with _debug_lock:
            if _active_debugger is None:
                return DebuggerState(status="idle")
            _active_debugger.stop()
            _active_debugger = None
        return DebuggerState(status="idle")

    @router.get("/state")
    async def debug_state(_admin: dict[str, Any] = Depends(_require_admin)) -> DebuggerState:
        with _debug_lock:
            if _active_debugger is None:
                return DebuggerState(status="idle")
            return _active_debugger.get_state()

    @router.post("/breakpoints")
    async def set_breakpoints(bps: list[BreakpointRequest], _admin: dict[str, Any] = Depends(_require_admin)) -> DebuggerState:
        with _debug_lock:
            if _active_debugger is None:
                raise HTTPException(400, "No active debug session")
            _active_debugger.set_breakpoints(bps)
            return _active_debugger.get_state()

    @router.post("/continue")
    async def debug_continue(_admin: dict[str, Any] = Depends(_require_admin)) -> DebuggerState:
        with _debug_lock:
            if _active_debugger is None:
                raise HTTPException(400, "No active debug session")
            _active_debugger.resume()
            return _active_debugger.get_state()

    @router.post("/step-over")
    async def debug_step_over(_admin: dict[str, Any] = Depends(_require_admin)) -> DebuggerState:
        with _debug_lock:
            if _active_debugger is None:
                raise HTTPException(400, "No active debug session")
            _active_debugger.step_over()
            return _active_debugger.get_state()

    @router.post("/step-into")
    async def debug_step_into(_admin: dict[str, Any] = Depends(_require_admin)) -> DebuggerState:
        with _debug_lock:
            if _active_debugger is None:
                raise HTTPException(400, "No active debug session")
            _active_debugger.step_into()
            return _active_debugger.get_state()

    return router


class _DebugSession:
    def __init__(self, file_path: Path, breakpoints: list[BreakpointRequest]) -> None:
        self._file_path = file_path
        self._resolved_str = str(file_path).replace("\\", "/")
        self._lock = threading.Lock()
        self._breakpoints: set[tuple[str, int]] = set()
        for bp in breakpoints:
            if bp.enabled:
                self._breakpoints.add((self._resolve_bp_path(bp.file), bp.line))
        self._status = "running"
        self._paused_file: str | None = None
        self._paused_line: int | None = None
        self._frames: list[dict[str, Any]] = []
        self._error: str | None = None
        self._step_mode: str | None = None
        self._step_depth = 0
        self._resume_event = threading.Event()
        self._resume_event.set()

    def _resolve_bp_path(self, user_path: str) -> str:
        if Path(user_path).is_absolute():
            target = confine_path(user_path, _get_workspace())
        else:
            target = confine_path(str(self._file_path.parent / user_path), _get_workspace())
        return str(target).replace("\\", "/")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._status = "stopped"
        self._resume_event.set()

    def set_breakpoints(self, bps: list[BreakpointRequest]) -> None:
        with self._lock:
            self._breakpoints = set()
            for bp in bps:
                if bp.enabled:
                    self._breakpoints.add((self._resolve_bp_path(bp.file), bp.line))

    def resume(self) -> None:
        with self._lock:
            self._status = "running"
            self._step_mode = None
        self._resume_event.set()

    def step_over(self) -> None:
        with self._lock:
            self._status = "running"
            self._step_mode = "over"
            self._step_depth = 0
        self._resume_event.set()

    def step_into(self) -> None:
        with self._lock:
            self._status = "running"
            self._step_mode = "into"
            self._step_depth = 1
        self._resume_event.set()

    def get_state(self) -> DebuggerState:
        with self._lock:
            return DebuggerState(
                status=self._status,
                paused_file=self._paused_file,
                paused_line=self._paused_line,
                frames=list(self._frames),
                error=self._error,
            )

    def _trace_dispatch(self, frame: FrameType | None, event: str, arg: Any) -> Any:
        with self._lock:
            status = self._status
            step_mode = self._step_mode
            step_depth = self._step_depth
        if status == "stopped":
            return None
        if frame is None:
            return self._trace_dispatch if event in ("call", "line", "return") else None
        if event == "call":
            new_depth = step_depth + 1 if step_mode == "into" else step_depth
            with self._lock:
                self._step_depth = new_depth
            return self._trace_dispatch
        if event == "line":
            filename = frame.f_code.co_filename.replace("\\", "/")
            lineno = frame.f_lineno
            with self._lock:
                should_stop = (filename, lineno) in self._breakpoints
                step_mode = self._step_mode
                step_depth = self._step_depth
            if should_stop:
                self._pause_at(frame, filename, lineno)
                return self._trace_dispatch
            if step_mode == "into" and step_depth == 0:
                self._pause_at(frame, filename, lineno)
                with self._lock:
                    self._step_mode = None
                return self._trace_dispatch
            if step_mode == "over" and step_depth == 0:
                self._pause_at(frame, filename, lineno)
                with self._lock:
                    self._step_mode = None
                return self._trace_dispatch
            return self._trace_dispatch
        if event == "return":
            with self._lock:
                step_mode = self._step_mode
                step_depth = self._step_depth
            if step_mode is not None and step_depth > 0:
                with self._lock:
                    self._step_depth -= 1
            return self._trace_dispatch
        return None

    def _pause_at(self, frame: FrameType, filename: str, lineno: int) -> None:
        f = _capture_frames_from(frame)
        with self._lock:
            self._status = "paused"
            self._paused_file = filename
            self._paused_line = lineno
            self._frames = f
        self._resume_event.clear()
        self._resume_event.wait()

    def _run(self) -> None:
        code = self._file_path.read_text("utf-8")
        compiled = compile(code, str(self._file_path), "exec")
        sys.settrace(self._trace_dispatch)
        try:
            import builtins as _builtins

            safe_builtins = {
                k: v
                for k, v in vars(_builtins).items()
                if k not in frozenset({"__import__", "exec", "eval", "compile", "open", "exit", "quit"})
            }
            ns: dict[str, object] = {
                "__name__": "__main__",
                "__file__": str(self._file_path),
                "__builtins__": safe_builtins,
            }
            exec(compiled, ns)
            with self._lock:
                if self._status not in ("stopped", "error"):
                    self._status = "running"
                    self._paused_file = None
                    self._paused_line = None
                    self._frames = []
        except SystemExit:
            with self._lock:
                self._status = "stopped"
        except Exception:
            tb = _sanitize_traceback(traceback.format_exc())
            frames = _capture_frames(exception=True)
            with self._lock:
                self._status = "error"
                self._error = tb
                self._frames = frames
        finally:
            sys.settrace(None)
            with self._lock:
                if self._status == "paused":
                    self._status = "stopped"
            self._resume_event.set()


def _capture_frames(exception: bool = False) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    tb = sys.exc_info()[2] if exception else None
    while tb:
        frame = tb.tb_frame
        frames.append(_frame_info(frame, tb.tb_lineno))
        tb = tb.tb_next
    return frames


def _capture_frames_from(frame: FrameType) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    f: FrameType | None = frame
    while f is not None:
        frames.append(_frame_info(f, f.f_lineno))
        f = f.f_back
    return frames


def _frame_info(frame: FrameType, lineno: int) -> dict[str, Any]:
    locals_safe: dict[str, str] = {}
    for k, v in frame.f_locals.items():
        try:
            raw = repr(v)[:200]
            for pat in _SANITIZE_PATTERNS:
                raw = pat.sub(lambda m: f"{m.group(1).split('=')[0].split(':')[0]}=***", raw)
            locals_safe[k] = raw
        except Exception:
            locals_safe[k] = "<unrepresentable>"
    return {
        "filename": frame.f_code.co_filename,
        "function": frame.f_code.co_name,
        "line": lineno,
        "locals": locals_safe,
    }

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import raven.core.debugger_api as dba
from raven.core.debugger_api import BreakpointRequest, _DebugSession

PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(autouse=True)
def _reset_debugger() -> Iterator[None]:
    dba._active_debugger = None
    yield
    active = dba._active_debugger
    if active is not None:
        active.stop()
    dba._active_debugger = None


@pytest.fixture()
def dbg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.py").write_text("x = 1\n", encoding="utf-8")
    (ws / "boom.py").write_text("raise ValueError('boom')\n", encoding="utf-8")
    (ws / "exit.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (ws / "pause.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (ws / "notes.txt").write_text("hi", encoding="utf-8")
    (ws / "big.py").write_text("# " + "x" * 600_000, encoding="utf-8")
    monkeypatch.setattr(dba, "_WORKSPACE", ws)
    app = FastAPI()
    app.include_router(dba.create_debugger_router())
    app.dependency_overrides[dba._require_admin] = lambda: {"role": "admin"}
    return TestClient(app), ws


def _session(file_path: Path, bps: list[BreakpointRequest] | None = None) -> _DebugSession:
    return _DebugSession(file_path, bps or [])


def _wait_until(session: _DebugSession, status: str, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if session.get_state().status == status:
            return True
        time.sleep(0.02)
    return False


# --- _get_workspace / _confine_path / _sanitize_traceback / _require_admin ---


def test_get_workspace_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dba, "_WORKSPACE", None)
    monkeypatch.delenv("RAVEN_WORKSPACE", raising=False)
    assert dba._get_workspace() == (PROJECT_ROOT / "workspace").resolve()


def test_get_workspace_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dba, "_WORKSPACE", None)
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    assert dba._get_workspace() == tmp_path.resolve()


def test_get_workspace_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dba, "_WORKSPACE", tmp_path)
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path / "other"))
    assert dba._get_workspace() == tmp_path.resolve()


def test_confine_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dba, "_WORKSPACE", tmp_path)
    assert dba._confine_path(str(tmp_path / "a.py")) == (tmp_path / "a.py").resolve()


def test_sanitize_traceback() -> None:
    tb = "raise ValueError at line 5\n    api_key='sk-1234567890abcdef'\n    token: abcdef\n    eyJhbGciOiJIUzI1NiJ9.xxxxx"
    out = dba._sanitize_traceback(tb)
    assert "sk-1234567890abcdef" not in out
    assert "api_key=***" in out
    assert "token=***" in out
    assert "=***" in out
    assert "eyJhbGciOiJIUzI1NiJ9.=***" in out


def _call_admin(role: object) -> dict[str, str]:
    req = cast(Any, SimpleNamespace(state=SimpleNamespace(user_role=role)))
    return asyncio.run(dba._require_admin(req))


def test_require_admin_allowed() -> None:
    assert _call_admin("admin") == {"role": "admin"}
    assert _call_admin("superadmin") == {"role": "superadmin"}


def test_require_admin_denied() -> None:
    with pytest.raises(HTTPException) as ei:
        _call_admin("user")
    assert ei.value.status_code == 403
    with pytest.raises(HTTPException):
        _call_admin(None)


# --- router endpoint tests ---


def test_start_success(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    resp = c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["frames"] == []
    c.post("/api/debug/stop")


def test_start_access_denied(dbg: tuple[TestClient, Path], tmp_path: Path) -> None:
    c, _ = dbg
    outside = tmp_path / "outside.py"
    outside.write_text("x=1\n", encoding="utf-8")
    resp = c.post("/api/debug/start", json={"file": str(outside)})
    assert resp.status_code == 403


def test_start_not_found(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    resp = c.post("/api/debug/start", json={"file": str(ws / "nope.py")})
    assert resp.status_code == 404


def test_start_wrong_extension(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    resp = c.post("/api/debug/start", json={"file": str(ws / "notes.txt")})
    assert resp.status_code == 403
    assert "Only .py" in resp.json()["detail"]


def test_start_too_large(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    resp = c.post("/api/debug/start", json={"file": str(ws / "big.py")})
    assert resp.status_code == 400
    assert "File too large" in resp.json()["detail"]


def test_start_replaces_existing(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    resp1 = c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    assert resp1.status_code == 200
    first = dba._active_debugger
    resp2 = c.post("/api/debug/start", json={"file": str(ws / "pause.py")})
    assert resp2.status_code == 200
    assert dba._active_debugger is not first


def test_stop_idle(dbg: tuple[TestClient, Path]) -> None:
    c, _ = dbg
    resp = c.post("/api/debug/stop")
    assert resp.status_code == 200
    assert resp.json() == {"status": "idle", "paused_file": None, "paused_line": None, "frames": [], "error": None}


def test_stop_active(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    resp = c.post("/api/debug/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"
    assert dba._active_debugger is None


def test_state_idle(dbg: tuple[TestClient, Path]) -> None:
    c, _ = dbg
    resp = c.get("/api/debug/state")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_state_active(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    resp = c.get("/api/debug/state")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_set_breakpoints_no_session(dbg: tuple[TestClient, Path]) -> None:
    c, _ = dbg
    resp = c.post("/api/debug/breakpoints", json=[{"file": "a.py", "line": 1, "enabled": True}])
    assert resp.status_code == 400


def test_set_breakpoints_with_session(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    resp = c.post(
        "/api/debug/breakpoints",
        json=[{"file": str(ws / "hello.py"), "line": 1, "enabled": True}],
    )
    assert resp.status_code == 200


def test_continue_no_session(dbg: tuple[TestClient, Path]) -> None:
    c, _ = dbg
    resp = c.post("/api/debug/continue")
    assert resp.status_code == 400


def test_continue_with_session(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    resp = c.post("/api/debug/continue")
    assert resp.status_code == 200


def test_step_over_no_session(dbg: tuple[TestClient, Path]) -> None:
    c, _ = dbg
    resp = c.post("/api/debug/step-over")
    assert resp.status_code == 400


def test_step_over_with_session(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    resp = c.post("/api/debug/step-over")
    assert resp.status_code == 200


def test_step_into_no_session(dbg: tuple[TestClient, Path]) -> None:
    c, _ = dbg
    resp = c.post("/api/debug/step-into")
    assert resp.status_code == 400


def test_step_into_with_session(dbg: tuple[TestClient, Path]) -> None:
    c, ws = dbg
    c.post("/api/debug/start", json={"file": str(ws / "hello.py")})
    resp = c.post("/api/debug/step-into")
    assert resp.status_code == 200


# --- _DebugSession unit tests ---


def test_session_init_filters_disabled_bps(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    bps = [
        BreakpointRequest(file="hello.py", line=1, enabled=True),
        BreakpointRequest(file="hello.py", line=5, enabled=False),
    ]
    s = _session(ws / "hello.py", bps)
    resolved = (ws / "hello.py").resolve().as_posix()
    assert s._breakpoints == {(resolved, 1)}
    assert s.get_state().status == "running"


def test_session_resolve_bp_absolute(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    assert s._resolve_bp_path(str(ws / "hello.py")) == (ws / "hello.py").resolve().as_posix()


def test_session_resolve_bp_relative(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    assert s._resolve_bp_path("hello.py") == (ws / "hello.py").resolve().as_posix()


def test_session_start_stop(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s.start()
    s._thread.join(timeout=5)
    s.stop()
    assert s.get_state().status == "stopped"


def test_session_resume(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s.resume()
    assert s.get_state().status == "running"
    assert s._step_mode is None


def test_session_step_over_sets_mode(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s.step_over()
    assert s._step_mode == "over"
    assert s._step_depth == 0
    assert s.get_state().status == "running"


def test_session_step_into_sets_mode(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s.step_into()
    assert s._step_mode == "into"
    assert s._step_depth == 1


def test_session_run_success(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s.start()
    s._thread.join(timeout=5)
    state = s.get_state()
    assert not s._thread.is_alive()
    assert state.status == "running"


def test_session_run_error(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "boom.py")
    s.start()
    s._thread.join(timeout=5)
    state = s.get_state()
    assert state.status == "error"
    assert "boom" in (state.error or "")
    assert state.frames


def test_session_run_system_exit(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "exit.py")
    s.start()
    s._thread.join(timeout=5)
    assert s.get_state().status == "stopped"


def test_session_run_breakpoint_pause(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "pause.py", [BreakpointRequest(file="pause.py", line=2, enabled=True)])
    s.start()
    try:
        assert _wait_until(s, "paused")
        state = s.get_state()
        assert state.paused_line == 2
        assert state.paused_file is not None and state.paused_file.endswith("pause.py")
        assert state.frames
        s.resume()
        s._thread.join(timeout=5)
        assert s.get_state().status == "running"
    finally:
        s.stop()


def test_session_stop_while_paused(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "pause.py", [BreakpointRequest(file="pause.py", line=2, enabled=True)])
    s.start()
    try:
        assert _wait_until(s, "paused")
        s.stop()
        s._thread.join(timeout=5)
        assert s.get_state().status == "stopped"
    finally:
        s.stop()


# --- _trace_dispatch unit tests (fake frames) ---


def _fake_frame(filename: str, lineno: int) -> Any:
    return SimpleNamespace(
        f_code=SimpleNamespace(co_filename=filename, co_name="f"),
        f_lineno=lineno,
        f_locals={},
        f_back=None,
    )


def test_trace_stopped(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s.stop()
    assert s._trace_dispatch(None, "line", None) is None


def test_trace_frame_none_non_trace_event(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    assert s._trace_dispatch(None, "exception", None) is None


def test_trace_call_into(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s._step_mode = "into"
    s._step_depth = 0
    result = s._trace_dispatch(_fake_frame("a.py", 1), "call", None)
    assert s._step_depth == 1
    assert callable(result)


def test_trace_call_plain(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s._step_depth = 2
    result = s._trace_dispatch(_fake_frame("a.py", 1), "call", None)
    assert s._step_depth == 2
    assert callable(result)


def test_trace_line_no_match(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    result = s._trace_dispatch(_fake_frame("other.py", 10), "line", None)
    assert callable(result)
    assert s.get_state().status == "running"


def test_trace_line_breakpoint_hit(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    target = (ws / "x.py").resolve().as_posix()
    s = _session(ws / "hello.py", [BreakpointRequest(file=str(ws / "x.py"), line=3, enabled=True)])
    timer = threading.Timer(0.15, s.resume)
    timer.start()
    try:
        result = s._trace_dispatch(_fake_frame(target, 3), "line", None)
    finally:
        timer.cancel()
    assert callable(result)


def test_trace_line_step_over(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s._step_mode = "over"
    s._step_depth = 0
    timer = threading.Timer(0.15, s.resume)
    timer.start()
    try:
        result = s._trace_dispatch(_fake_frame("a.py", 1), "line", None)
    finally:
        timer.cancel()
    assert callable(result)
    assert s._step_mode is None


def test_trace_line_step_into(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s._step_mode = "into"
    s._step_depth = 0
    timer = threading.Timer(0.15, s.resume)
    timer.start()
    try:
        result = s._trace_dispatch(_fake_frame("a.py", 1), "line", None)
    finally:
        timer.cancel()
    assert callable(result)
    assert s._step_mode is None


def test_trace_return_decrement(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s._step_depth = 2
    s._step_mode = "into"
    result = s._trace_dispatch(_fake_frame("a.py", 1), "return", None)
    assert s._step_depth == 1
    assert callable(result)


def test_trace_return_no_decrement(dbg: tuple[TestClient, Path]) -> None:
    _, ws = dbg
    s = _session(ws / "hello.py")
    s._step_depth = 0
    result = s._trace_dispatch(_fake_frame("a.py", 1), "return", None)
    assert s._step_depth == 0
    assert callable(result)


# --- frame capture helpers ---


def test_capture_frames_exception() -> None:
    frames: list[dict[str, object]] = []
    try:
        raise ValueError("x")
    except ValueError:
        frames = dba._capture_frames(exception=True)
    assert frames
    assert frames[0]["function"] == "test_capture_frames_exception"


def test_capture_frames_from() -> None:
    frame = inspect.currentframe()
    assert frame is not None
    frames = dba._capture_frames_from(frame)
    assert frames
    assert frames[0]["filename"].replace("\\", "/").endswith("test_debugger_api.py")


class _BadRepr:
    def __repr__(self) -> str:
        raise RuntimeError("unrepresentable")


def test_frame_info_sanitizes_locals() -> None:
    token_line = "api_key=sk-1234567890abcdef"
    assert token_line.startswith("api_key")
    bad = _BadRepr()
    assert isinstance(bad, _BadRepr)
    frame = inspect.currentframe()
    assert frame is not None
    info = dba._frame_info(frame, frame.f_lineno)
    assert "token_line" in info["locals"]
    assert "sk-1234567890abcdef" not in info["locals"]["token_line"]
    assert "api_key=***" in info["locals"]["token_line"]
    assert info["locals"]["bad"] == "<unrepresentable>"
    assert info["filename"].replace("\\", "/").endswith("test_debugger_api.py")

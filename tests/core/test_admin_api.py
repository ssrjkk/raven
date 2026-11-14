from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterator, MutableMapping
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from raven.core.auth.models import Permission, Role
from raven.core.monitor.models import MonitorStatus, MonitorType
from raven.core.monitor.store import MonitorStore


class _StateMiddleware:
    def __init__(self, app: ASGIApp, state: dict[str, str]) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {}).update(self.state)
        await self.app(scope, receive, send)


class FakeDb:
    def __init__(self) -> None:
        self.sessions = [
            SimpleNamespace(id="s1", channel="telegram", user_id="u1"),
            SimpleNamespace(id="s2", channel="web", user_id="u2"),
        ]

    async def get_sessions(self) -> list[SimpleNamespace]:
        return self.sessions


class FakeGateway:
    def __init__(self, db_path: Path) -> None:
        self._monitor_store = MonitorStore(str(db_path))
        self.db = FakeDb()
        self._running = True


class FakeChannel:
    def __init__(self, ready: bool = True) -> None:
        self._ready = ready

    def stats(self) -> dict[str, int]:
        return {"messages": 3}


class FakeRegistry:
    def __init__(self) -> None:
        self.agents = [{"id": "primary", "name": "Primary Agent"}]
        self.defaults_called = 0

    def list_agents(self) -> list[dict[str, str]]:
        return self.agents

    def setup_defaults(self) -> None:
        self.defaults_called += 1


class FakeSecrets:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def list_keys(self) -> list[str]:
        return list(self.data)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def unset(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[MonitorStore]:
    s = MonitorStore(str(tmp_path / "admin.db"))
    yield s
    asyncio.run(s.close())


@pytest.fixture
def gateway(tmp_path: Path) -> Iterator[FakeGateway]:
    gw = FakeGateway(tmp_path / "admin.db")
    yield gw
    asyncio.run(gw._monitor_store.close())


@pytest.fixture
def registry() -> FakeRegistry:
    return FakeRegistry()


@pytest.fixture
def channels() -> dict[str, FakeChannel]:
    return {"telegram": FakeChannel(ready=True), "web": FakeChannel(ready=False)}


def _first_body_chunk(app: FastAPI, path: str) -> str:
    import contextlib

    async def _run() -> str:
        scope: MutableMapping[str, Any] = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 123),
            "state": {},
            "app": app,
        }
        received: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

        async def send(message: MutableMapping[str, Any]) -> None:
            received.append(dict(message))

        task = asyncio.create_task(app(scope, receive, send))
        for _ in range(100):
            await asyncio.sleep(0.05)
            if any(m["type"] == "http.response.body" and m.get("body") for m in received):
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        body = next((m for m in received if m["type"] == "http.response.body" and m.get("body")), None)
        if body is None:
            return ""
        raw: bytes = body["body"]
        return raw.decode("utf-8")

    return asyncio.run(_run())


def _make_client(gateway, registry, channels, role: str | None = None) -> TestClient:
    from raven.core.admin_api import create_admin_router

    app = FastAPI()
    state = {"user_role": role, "user_id": "admin1"} if role else {}
    app.add_middleware(_StateMiddleware, state=state)
    app.include_router(
        create_admin_router(
            lambda: channels,
            lambda: registry,
            lambda: gateway,
        )
    )
    return TestClient(app)


def _create_monitor(store: MonitorStore, name: str = "disk", target: str = "/tmp/x") -> str:
    import time

    from raven.core.monitor.models import Monitor

    m = Monitor(
        name=name,
        type=MonitorType.FILE,
        target=target,
        interval_seconds=60,
        status=MonitorStatus.ACTIVE,
        created_at=time.time(),
    )

    async def _save() -> None:
        await store.save_monitor(m)

    asyncio.run(_save())
    return m.id


class TestMonitors:
    def test_create_list_get_update_delete(self, gateway, registry, channels, tmp_path: Path) -> None:
        client = _make_client(gateway, registry, channels)
        payload = {
            "name": "disk-space",
            "type": "file",
            "target": str(tmp_path / "app.log"),
            "interval_seconds": 60,
            "conditions": [{"metric": "size", "operator": ">", "value": 100}],
        }
        resp = client.post("/api/admin/monitors", json=payload)
        assert resp.status_code == 200
        mid = resp.json()["id"]

        lst = client.get("/api/admin/monitors").json()
        assert len(lst) == 1
        assert lst[0]["name"] == "disk-space"
        assert lst[0]["type"] == "file"

        detail = client.get(f"/api/admin/monitors/{mid}").json()
        assert detail["id"] == mid
        assert detail["conditions"][0]["metric"] == "size"

        upd = client.put(f"/api/admin/monitors/{mid}", json={"name": "renamed", "cooldown_minutes": 5})
        assert upd.status_code == 200
        assert client.get(f"/api/admin/monitors/{mid}").json()["name"] == "renamed"

        deleted = client.delete(f"/api/admin/monitors/{mid}")
        assert deleted.status_code == 200
        assert client.get("/api/admin/monitors").json() == []

    def test_monitor_filter_by_user(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        _create_monitor(gateway._monitor_store, name="mine")
        resp = client.get("/api/admin/monitors", params={"user_id": "nobody"})
        assert resp.json() == []

    def test_get_missing_monitor_404(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/monitors/nope").status_code == 404
        assert client.put("/api/admin/monitors/nope", json={"name": "x"}).status_code == 404
        assert client.delete("/api/admin/monitors/nope").status_code == 404

    def test_check_now_file_exists(self, gateway, registry, channels, tmp_path: Path) -> None:
        target = tmp_path / "ok.txt"
        target.write_text("hello", encoding="utf-8")
        mid = _create_monitor(gateway._monitor_store, target=str(target))
        client = _make_client(gateway, registry, channels)
        resp = client.post(f"/api/admin/monitors/{mid}/check")
        assert resp.status_code == 200
        assert resp.json()["triggered"] is False

    def test_check_now_file_missing_alert(self, gateway, registry, channels, tmp_path: Path) -> None:
        mid = _create_monitor(gateway._monitor_store, target=str(tmp_path / "missing.log"))
        client = _make_client(gateway, registry, channels)
        resp = client.post(f"/api/admin/monitors/{mid}/check")
        assert resp.status_code == 200
        assert resp.json()["triggered"] is True
        assert "alert" not in resp.json()

    def test_pause_and_resume(self, gateway, registry, channels, tmp_path: Path) -> None:
        from raven.core.monitor.engine import MonitorEngine

        gateway._monitor_engine = MonitorEngine(gateway._monitor_store)
        mid = _create_monitor(gateway._monitor_store)
        client = _make_client(gateway, registry, channels)
        assert client.post(f"/api/admin/monitors/{mid}/pause").json() == {"ok": True, "status": "paused"}
        assert client.get(f"/api/admin/monitors/{mid}").json()["status"] == "paused"
        assert client.post(f"/api/admin/monitors/{mid}/resume").json() == {"ok": True, "status": "active"}
        assert client.get(f"/api/admin/monitors/{mid}").json()["status"] == "active"

    def test_pause_without_an_engine_still_reaches_the_store(self, gateway, registry, channels) -> None:
        # The handler used to answer `{"ok": true}` and write nothing when no engine was mounted, so the
        # monitor kept firing while the console was told it was paused. The status is what an engine reads
        # back when it starts, so the write has to happen with or without one.
        assert not hasattr(gateway, "_monitor_engine")
        mid = _create_monitor(gateway._monitor_store)
        client = _make_client(gateway, registry, channels)
        assert client.post(f"/api/admin/monitors/{mid}/pause").json() == {"ok": True, "status": "paused"}
        assert client.get(f"/api/admin/monitors/{mid}").json()["status"] == "paused"
        assert client.post(f"/api/admin/monitors/{mid}/resume").json() == {"ok": True, "status": "active"}
        assert client.get(f"/api/admin/monitors/{mid}").json()["status"] == "active"

    def test_monitor_commands_on_an_unknown_id_do_not_answer_ok(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.post("/api/admin/monitors/nope/pause").status_code == 404
        assert client.post("/api/admin/monitors/nope/resume").status_code == 404
        assert client.post("/api/admin/monitors/nope/check").status_code == 404

    def test_editing_a_status_reaches_the_mounted_engine(self, gateway, registry, channels) -> None:
        calls: list[str] = []

        class _RecordingEngine:
            async def pause_monitor(self, monitor_id: str) -> bool:
                calls.append(f"pause:{monitor_id}")
                return True

            async def resume_monitor(self, monitor_id: str) -> bool:
                calls.append(f"resume:{monitor_id}")
                return True

        gateway._monitor_engine = _RecordingEngine()
        mid = _create_monitor(gateway._monitor_store)
        client = _make_client(gateway, registry, channels)
        assert client.put(f"/api/admin/monitors/{mid}", json={"status": "paused"}).status_code == 200
        assert calls == [f"pause:{mid}"]
        assert client.put(f"/api/admin/monitors/{mid}", json={"status": "active"}).status_code == 200
        assert calls == [f"pause:{mid}", f"resume:{mid}"]

    def test_check_now_runs_on_the_mounted_engine(self, gateway, registry, channels, tmp_path: Path) -> None:
        # A hand-triggered check has to run on the engine the gateway started. The throwaway engine it used
        # to build keeps its own alert clock, so the cooldown history never reached the scheduled runs.
        from raven.core.monitor.engine import MonitorEngine

        mid = _create_monitor(gateway._monitor_store, target=str(tmp_path / "gone.log"))
        engine = MonitorEngine(gateway._monitor_store)
        gateway._monitor_engine = engine
        client = _make_client(gateway, registry, channels)
        assert client.post(f"/api/admin/monitors/{mid}/check").json() == {"ok": True, "triggered": True}
        assert mid in engine._last_alert_at

    def test_full_update_all_fields(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        payload = {
            "name": "orig",
            "type": "file",
            "target": "/tmp/orig",
            "interval_seconds": 60,
            "cooldown_minutes": 30,
        }
        mid = client.post("/api/admin/monitors", json=payload).json()["id"]
        update = {
            "name": "renamed",
            "type": "http",
            "target": "https://api.example.com",
            "interval_seconds": 120,
            "status": "paused",
            "user_id": "u9",
            "channel": "web",
            "cooldown_minutes": 5,
            "config": {"foo": "bar"},
            "conditions": [{"metric": "latency", "operator": ">", "value": 5}],
        }
        resp = client.put(f"/api/admin/monitors/{mid}", json=update)
        assert resp.status_code == 200
        detail = client.get(f"/api/admin/monitors/{mid}").json()
        assert detail["name"] == "renamed"
        assert detail["type"] == "http"
        assert detail["interval_seconds"] == 120
        assert detail["status"] == "paused"
        assert detail["user_id"] == "u9"
        assert detail["channel"] == "web"
        assert detail["cooldown_minutes"] == 5
        assert detail["conditions"][0]["metric"] == "latency"

    def test_ssrf_rejected_at_model(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        resp = client.post(
            "/api/admin/monitors", json={"name": "bad", "type": "http", "target": "http://localhost:8080"}
        )
        assert resp.status_code == 422


class TestSystem:
    def test_health_and_ready(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/health").status_code == 200
        assert client.get("/api/admin/health/ready").status_code == 200

    def test_metrics(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        resp = client.get("/api/admin/metrics")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)
        prom = client.get("/api/admin/metrics/prometheus")
        assert prom.status_code == 200

    def test_channels_list_and_get(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        lst = client.get("/api/admin/channels").json()
        assert {c["id"] for c in lst} == {"telegram", "web"}
        assert lst[0]["stats"] == {"messages": 3}
        detail = client.get("/api/admin/channels/telegram").json()
        assert detail["ready"] is True
        assert client.get("/api/admin/channels/unknown").status_code == 404

    def test_channel_restart(self, gateway, registry, channels) -> None:
        import asyncio

        class RestartChannel(FakeChannel):
            async def start(self) -> None:
                self._ready = True

            async def stop(self) -> None:
                self._ready = False

        ch = RestartChannel(ready=False)
        channels["rc"] = ch
        client = _make_client(gateway, registry, channels)
        resp = client.post("/api/admin/channels/rc/restart")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "channel": "rc"}
        assert ch._ready is True

    def test_channel_restart_error_500(self, gateway, registry, channels) -> None:
        class BadChannel(FakeChannel):
            async def start(self) -> None:
                msg = "cannot start"
                raise RuntimeError(msg)

            async def stop(self) -> None:
                return None

        channels["bad"] = BadChannel()
        client = _make_client(gateway, registry, channels)
        assert client.post("/api/admin/channels/bad/restart").status_code == 500

    def test_channel_restart_404(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.post("/api/admin/channels/missing/restart").status_code == 404

    def test_agents_and_reload(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/agents").json() == [{"id": "primary", "name": "Primary Agent"}]
        resp = client.post("/api/admin/agents/primary/reload")
        assert resp.status_code == 200
        assert registry.defaults_called == 1

    def test_agent_reload_error_500(self, gateway, registry, channels) -> None:
        def boom() -> None:
            msg = "reload failed"
            raise RuntimeError(msg)

        registry.setup_defaults = boom
        client = _make_client(gateway, registry, channels)
        assert client.post("/api/admin/agents/primary/reload").status_code == 500

    def test_oauth_callback_success(self, gateway, registry, channels, monkeypatch) -> None:
        import raven.core.auth.oauth as oauth_mod
        import raven.core.auth.tokens as tokens_mod

        async def fake_callback(provider: str, code: str, state: str):
            return {"user_id": "u1", "username": "alice"}

        monkeypatch.setattr(oauth_mod, "handle_callback", fake_callback)
        monkeypatch.setattr(tokens_mod.token_manager, "create_token", AsyncMock(return_value="tok-123"))
        client = _make_client(gateway, registry, channels)
        resp = client.post("/api/admin/auth/oauth/callback/github", json={"code": "c", "state": "s"})
        assert resp.status_code == 200
        assert resp.json()["token"] == "tok-123"

    def test_oauth_callback_github_persists_token(self, gateway, registry, channels, monkeypatch) -> None:
        import raven.core.auth.oauth as oauth_mod
        import raven.core.auth.tokens as tokens_mod
        from raven.core.secrets import secrets

        async def fake_callback(provider: str, code: str, state: str):
            return {"user_id": "gh1", "username": "ghuser", "access_token": "gh-token", "scope": "repo read"}

        recorded: dict[str, str] = {}

        async def fake_set(key: str, value: str) -> None:
            recorded[key] = value

        monkeypatch.setattr(oauth_mod, "handle_callback", fake_callback)
        monkeypatch.setattr(tokens_mod.token_manager, "create_token", AsyncMock(return_value="tok-gh"))
        monkeypatch.setattr(secrets, "set", fake_set)
        client = _make_client(gateway, registry, channels)
        resp = client.post("/api/admin/auth/oauth/callback/github", json={"code": "c", "state": "s"})
        assert resp.status_code == 200
        assert recorded == {"github_oauth_token": "gh-token"}
        assert "access_token" not in resp.json()

    def test_oauth_callback_failure_401(self, gateway, registry, channels, monkeypatch) -> None:
        import raven.core.auth.oauth as oauth_mod

        async def fake_callback(provider: str, code: str, state: str):
            return None

        monkeypatch.setattr(oauth_mod, "handle_callback", fake_callback)
        client = _make_client(gateway, registry, channels)
        resp = client.post("/api/admin/auth/oauth/callback/github", json={"code": "c", "state": "s"})
        assert resp.status_code == 401

    def test_logs_stream_heartbeat(self, gateway, registry, channels) -> None:
        from raven.core.admin_api import create_admin_router

        app = FastAPI()
        app.include_router(create_admin_router(lambda: channels, lambda: registry, lambda: gateway))
        first = _first_body_chunk(app, "/api/admin/logs/stream")
        assert first.startswith("data: ")

    def test_sessions(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/sessions").json() == [
            {"id": "s1", "channel": "telegram", "user_id": "u1"},
            {"id": "s2", "channel": "web", "user_id": "u2"},
        ]

    def test_audit_endpoints(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/audit").status_code == 200
        assert client.get("/api/admin/audit/stats").status_code == 200
        verify = client.get("/api/admin/audit/verify").json()
        assert "chain" in verify and "signatures" in verify

    def test_config(self, gateway, registry, channels) -> None:
        """The screen renders whatever keys this answers, so the answer has to be the writable set."""
        from raven.core.config import console_config_keys, settings

        client = _make_client(gateway, registry, channels)
        body = client.get("/api/admin/config").json()
        assert set(body) == set(console_config_keys())
        assert body["web_port"] == settings.web_port
        assert not [key for key in body if key.endswith("_api_key")]

    def test_system_status(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        body = client.get("/api/admin/system/status").json()
        assert body["channels"] == 2
        assert body["agents"] == 1
        assert body["running"] is True

    def test_jobs_list(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/jobs").status_code == 200

    def test_job_cancel_unknown(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        resp = client.delete("/api/admin/jobs/unknown-id")
        assert resp.status_code == 200
        assert "ok" in resp.json()

    def test_shutdown_forbidden_without_role(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.post("/api/admin/shutdown").status_code == 403

    def test_shutdown_refuses_every_role_the_permission_excludes(self, gateway, registry, channels) -> None:
        for role in ("user", "viewer", "banned", "superadmin", ""):
            client = _make_client(gateway, registry, channels, role=role)
            assert client.post("/api/admin/shutdown").status_code == 403, role

    def test_shutdown_allowed_with_admin(self, gateway, registry, channels) -> None:
        from raven.core.admin_api import create_admin_router

        app = FastAPI()
        app.state.stop_event = asyncio.Event()
        app.add_middleware(_StateMiddleware, state={"user_role": "admin"})
        app.include_router(create_admin_router(lambda: channels, lambda: registry, lambda: gateway))
        client = TestClient(app)
        resp = client.post("/api/admin/shutdown")
        assert resp.status_code == 200
        assert app.state.stop_event.is_set()


class TestWorkflows:
    def test_list_and_categories(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        lst = client.get("/api/admin/workflows").json()
        assert isinstance(lst, list)
        cats = client.get("/api/admin/workflow-categories").json()
        assert isinstance(cats["categories"], list)

    def test_detail_and_missing(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        lst = client.get("/api/admin/workflows").json()
        assert lst
        tid = lst[0]["id"]
        detail = client.get(f"/api/admin/workflows/{tid}")
        assert detail.status_code == 200
        assert detail.json()["id"] == tid
        assert client.get("/api/admin/workflows/does-not-exist").status_code == 404

    def test_category_filter(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        all_wf = client.get("/api/admin/workflows").json()
        cats = {w["category"] for w in all_wf}
        for c in list(cats)[:1]:
            filtered = client.get("/api/admin/workflows", params={"category": c}).json()
            assert filtered and all(w["category"] == c for w in filtered)

    def test_update_steps_roundtrip(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        lst = client.get("/api/admin/workflows").json()
        tid = lst[0]["id"]
        body = {"steps": [{"description": "Step A", "tool": None, "params": {"k": "v"}}]}
        r = client.put(f"/api/admin/workflows/{tid}/steps", json=body)
        assert r.status_code == 200
        detail = client.get(f"/api/admin/workflows/{tid}").json()
        assert detail["predefined_steps"] == [{"description": "Step A", "tool": None, "params": {"k": "v"}}]
        assert client.put("/api/admin/workflows/does-not-exist/steps", json=body).status_code == 404

    def test_generate_steps(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        lst = client.get("/api/admin/workflows").json()
        tid = next(w["id"] for w in lst if w["steps_goal"])
        r = client.post(f"/api/admin/workflows/{tid}/generate-steps")
        assert r.status_code == 200
        steps = r.json()["steps"]
        assert steps and all(s["description"] for s in steps)
        assert client.post("/api/admin/workflows/does-not-exist/generate-steps").status_code == 404


class TestSecrets:
    def test_secrets_require_admin(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/secrets").status_code == 403
        assert client.post("/api/admin/secrets/KEY", json={"value": "v"}).status_code == 403
        assert client.delete("/api/admin/secrets/KEY").status_code == 403

    def test_secrets_refuse_every_role_the_permission_excludes(self, gateway, registry, channels) -> None:
        for role in ("user", "viewer", "banned", "superadmin", ""):
            client = _make_client(gateway, registry, channels, role=role)
            assert client.get("/api/admin/secrets").status_code == 403, role
            assert client.post("/api/admin/secrets/KEY", json={"value": "v"}).status_code == 403, role
            assert client.delete("/api/admin/secrets/KEY").status_code == 403, role

    def test_secrets_crud_with_admin(self, gateway, registry, channels, monkeypatch) -> None:
        import raven.core.admin_api as admin_api

        fake = FakeSecrets()
        monkeypatch.setattr(admin_api, "secrets", fake)
        client = _make_client(gateway, registry, channels, role="admin")
        assert client.get("/api/admin/secrets").json() == {"keys": []}
        assert client.post("/api/admin/secrets/API_KEY", json={"value": "sk-test"}).status_code == 200
        assert client.get("/api/admin/secrets").json() == {"keys": ["API_KEY"]}
        assert client.delete("/api/admin/secrets/API_KEY").status_code == 200
        assert client.get("/api/admin/secrets").json() == {"keys": []}


class TestConfigKey:
    def test_forbidden_without_role(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        resp = client.post("/api/admin/config/key", json={"key": "default_model", "value": "gpt-4o"})
        assert resp.status_code == 403

    def test_refuses_every_role_the_permission_excludes(self, gateway, registry, channels) -> None:
        for role in ("user", "viewer", "banned", "superadmin"):
            client = _make_client(gateway, registry, channels, role=role)
            resp = client.post("/api/admin/config/key", json={"key": "default_model", "value": "gpt-4o"})
            assert resp.status_code == 403, role

    def test_the_permission_the_guard_uses_is_admin_only(self, gateway, registry, channels) -> None:
        """The endpoints became permission checks, so which permission they picked is the contract."""
        from raven.core.auth.models import ROLE_PERMISSIONS
        from raven.core.auth.rbac import rbac

        for permission in (Permission.ADMIN_WRITE, Permission.ADMIN_SECRETS, Permission.SYSTEM_SHUTDOWN):
            granted = [r.value for r in ROLE_PERMISSIONS if rbac.has_permission(r.value, permission)]
            assert granted == ["admin"], permission

    def test_disallowed_key(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels, role="admin")
        resp = client.post("/api/admin/config/key", json={"key": "secret_stuff", "value": "x"})
        assert resp.status_code == 403

    def test_allowed_key_update(self, gateway, registry, channels, switch_env) -> None:
        """A write has to move the running gateway, not a file nobody reads."""
        from raven.core.config import settings

        client = _make_client(gateway, registry, channels, role="admin")
        resp = client.post("/api/admin/config/key", json={"key": "default_model", "value": "gpt-4o"})
        assert resp.status_code == 200
        assert resp.json()["applied"] is True
        assert settings.default_model == "gpt-4o"
        assert "DEFAULT_MODEL=gpt-4o" in switch_env.read_text(encoding="utf-8")

    def test_a_value_the_gateway_could_not_act_on_answers_400(self, gateway, registry, channels, switch_env) -> None:
        client = _make_client(gateway, registry, channels, role="admin")
        resp = client.post("/api/admin/config/key", json={"key": "dm_policy", "value": "sometimes"})
        assert resp.status_code == 400
        assert "DM_POLICY must be one of" in resp.json()["detail"]
        assert switch_env.read_text(encoding="utf-8") == ""

    def test_a_rotated_credential_is_never_echoed_back(self, gateway, registry, channels, switch_env) -> None:
        """The apply response goes straight to the browser and the audit trail, so the value must not be in it."""
        client = _make_client(gateway, registry, channels, role="admin")
        resp = client.post(
            "/api/admin/config/key",
            json={"key": "openrouter_api_key", "value": "sk-or-v1-0123456789abcdef0123456789abcdef"},
        )
        assert resp.status_code == 200
        assert "value" not in resp.json()
        assert "sk-or-v1-0123456789abcdef0123456789abcdef" not in resp.text

    def test_a_restart_bound_switch_says_so_instead_of_claiming_it_applied(
        self, gateway, registry, channels, switch_env
    ) -> None:
        from raven.core.config import settings

        client = _make_client(gateway, registry, channels, role="admin")
        resp = client.post("/api/admin/config/key", json={"key": "web_port", "value": "9999"})
        body = resp.json()
        assert body["applied"] is False
        assert body["restart_required"] is True
        assert body["warnings"], body
        assert settings.web_port != 9999
        assert "WEB_PORT=9999" in switch_env.read_text(encoding="utf-8")


class TestTheGuardAnswersThePermissionTable:
    """A handler that hard-coded `role == "admin"` still 403s here even though the denial tests pass.

    Granting the permission to `viewer` through the role table is the only way to tell a check that
    asks the table from one that asks the role name — and the two also differ on which right a caller
    needs, so each endpoint is offered a neighbouring permission as well.
    """

    def test_secrets_open_for_a_role_the_table_grants(
        self, gateway, registry, channels, monkeypatch, grant_permission
    ) -> None:
        import raven.core.admin_api as admin_api

        monkeypatch.setattr(admin_api, "secrets", FakeSecrets())
        grant_permission(Role.VIEWER.value, Permission.ADMIN_SECRETS)
        client = _make_client(gateway, registry, channels, role="viewer")
        assert client.get("/api/admin/secrets").status_code == 200

    def test_secrets_stay_closed_for_a_different_admin_right(
        self, gateway, registry, channels, grant_permission
    ) -> None:
        grant_permission(Role.VIEWER.value, Permission.ADMIN_WRITE)
        client = _make_client(gateway, registry, channels, role="viewer")
        assert client.get("/api/admin/secrets").status_code == 403
        assert client.post("/api/admin/secrets/KEY", json={"value": "v"}).status_code == 403
        assert client.delete("/api/admin/secrets/KEY").status_code == 403

    def test_config_open_for_a_role_the_table_grants(
        self, gateway, registry, channels, monkeypatch, grant_permission, switch_env
    ) -> None:
        """`dm_policy` rather than `log_level`: the guard is the subject, and a log-level write rebuilds
        the process-wide loguru sinks the rest of the run is still using."""
        from raven.core.config import settings

        grant_permission(Role.VIEWER.value, Permission.ADMIN_WRITE)
        client = _make_client(gateway, registry, channels, role="viewer")
        resp = client.post("/api/admin/config/key", json={"key": "dm_policy", "value": "open"})
        assert resp.status_code == 200
        assert settings.dm_policy == "open"

    def test_config_stays_closed_for_a_secrets_right(self, gateway, registry, channels, grant_permission) -> None:
        grant_permission(Role.VIEWER.value, Permission.ADMIN_SECRETS)
        client = _make_client(gateway, registry, channels, role="viewer")
        assert client.post("/api/admin/config/key", json={"key": "log_level", "value": "x"}).status_code == 403

    def test_shutdown_open_for_a_role_the_table_grants(self, gateway, registry, channels, grant_permission) -> None:
        grant_permission(Role.VIEWER.value, Permission.SYSTEM_SHUTDOWN)
        client = _make_client(gateway, registry, channels, role="viewer")
        assert client.post("/api/admin/shutdown").status_code == 200

    def test_shutdown_stays_closed_for_a_write_right(self, gateway, registry, channels, grant_permission) -> None:
        grant_permission(Role.VIEWER.value, Permission.ADMIN_WRITE)
        client = _make_client(gateway, registry, channels, role="viewer")
        assert client.post("/api/admin/shutdown").status_code == 403

    def test_model_switch_answers_the_table(self, gateway, registry, channels, monkeypatch, grant_permission) -> None:
        """The pull is gigabytes, so the real enable/disable are patched out and only the guard is tested."""
        import raven.core.heretic_model as hm

        monkeypatch.setattr(hm, "disable", lambda: SimpleNamespace(ok=True, detail="off"))
        monkeypatch.setattr(hm, "enable", lambda *a, **k: SimpleNamespace(ok=True, detail="on"))
        body = {"action": "disable", "force": False}
        client = _make_client(gateway, registry, channels, role="viewer")
        assert client.post("/api/admin/models/experimental", json=body).status_code == 403
        grant_permission(Role.VIEWER.value, Permission.ADMIN_WRITE)
        assert client.post("/api/admin/models/experimental", json=body).status_code == 200


class TestOAuth:
    def test_providers_endpoint(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        resp = client.get("/api/admin/auth/oauth/providers")
        assert resp.status_code == 200
        assert "providers" in resp.json()

    def test_authorize_unknown_provider_400(self, gateway, registry, channels) -> None:
        client = _make_client(gateway, registry, channels)
        resp = client.get("/api/admin/auth/oauth/authorize/nope")
        assert resp.status_code == 400

    def test_authorize_enabled_provider(self, gateway, registry, channels, monkeypatch) -> None:
        import raven.core.auth.oauth as oauth_mod

        monkeypatch.setattr(oauth_mod, "get_authorize_url", lambda p, u: f"https://auth.example/{p}")
        client = _make_client(gateway, registry, channels)
        resp = client.get("/api/admin/auth/oauth/authorize/github")
        assert resp.status_code == 200
        assert "url" in resp.json()


class TestAuthRoutes:
    @pytest.fixture
    def auth_client(self, tmp_path: Path) -> Iterator[TestClient]:
        from raven.core.admin_api import init_auth_routes

        app = FastAPI()
        init_auth_routes(app, str(tmp_path / "auth.db"))
        # The context manager runs the lifespan, which closes the auth store.
        with TestClient(app) as client:
            yield client

    def test_register_and_login(self, auth_client) -> None:
        reg = auth_client.post("/api/auth/register", json={"username": "alice", "password": "Secret123!"})
        assert reg.status_code == 200
        token = reg.json()["token"]
        assert token

        login = auth_client.post("/api/auth/login", json={"username": "alice", "password": "Secret123!"})
        assert login.status_code == 200
        assert login.json()["role"] == "user"

    def test_login_wrong_password(self, auth_client) -> None:
        auth_client.post("/api/auth/register", json={"username": "bob", "password": "Secret123!"})
        resp = auth_client.post("/api/auth/login", json={"username": "bob", "password": "wrong-pw"})
        assert resp.status_code == 401

    def test_login_unknown_user(self, auth_client) -> None:
        resp = auth_client.post("/api/auth/login", json={"username": "ghost", "password": "whatever"})
        assert resp.status_code == 401

    def test_register_duplicate(self, auth_client) -> None:
        auth_client.post("/api/auth/register", json={"username": "carol", "password": "Secret123!"})
        resp = auth_client.post("/api/auth/register", json={"username": "carol", "password": "Secret123!"})
        assert resp.status_code == 409

    def test_register_short_password(self, auth_client) -> None:
        resp = auth_client.post("/api/auth/register", json={"username": "dave", "password": "123"})
        assert resp.status_code == 422

    def test_register_with_display_name(self, auth_client) -> None:
        resp = auth_client.post(
            "/api/auth/register", json={"username": "erin", "password": "Secret123!", "display_name": "Erin R."}
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "erin"

    def test_login_rate_limit(self, auth_client) -> None:
        for _ in range(5):
            auth_client.post("/api/auth/login", json={"username": "x", "password": "bad"})
        resp = auth_client.post("/api/auth/login", json={"username": "x", "password": "bad"})
        assert resp.status_code == 429

    def test_me_defaults_anonymous(self, auth_client) -> None:
        body = auth_client.get("/api/auth/me").json()
        assert body == {"user_id": "anonymous", "role": "anonymous"}
        # Only the handler is in this app: the gateway's own surface refuses an anonymous private
        # read before the route runs, which tests/test_aios_e2e.py asserts over the real middleware.
        assert auth_client.get("/api/auth/me", headers={"Authorization": "Bearer revoked-token"}).status_code == 200

    def test_logout_without_token(self, auth_client) -> None:
        assert auth_client.post("/api/auth/logout").status_code == 200

    def test_logout_with_token(self, auth_client) -> None:
        resp = auth_client.post("/api/auth/logout", headers={"Authorization": "Bearer some-token"})
        assert resp.status_code == 200

    def test_sse_stream(self, tmp_path: Path) -> None:
        from raven.core.admin_api import init_auth_routes

        app = FastAPI()
        init_auth_routes(app, str(tmp_path / "auth.db"))
        try:
            first = _first_body_chunk(app, "/api/stream")
        finally:
            # This test drives the ASGI app directly, so no lifespan runs to close the store.
            asyncio.run(app.state.auth_store.close())
        assert "connected" in first
        assert "data:" in first

    def test_users_list_and_role_update(self, auth_client) -> None:
        auth_client.post("/api/auth/register", json={"username": "frank", "password": "Secret123!"})
        users = auth_client.get("/api/auth/users").json()
        assert any(u["username"] == "frank" for u in users)
        resp = auth_client.post("/api/auth/users/frank/role", json={"role": "admin"})
        assert resp.status_code == 200
        users = auth_client.get("/api/auth/users").json()
        frank = next(u for u in users if u["username"] == "frank")
        assert frank["role"] == "admin"

    def test_role_update_missing_user_noop(self, auth_client) -> None:
        resp = auth_client.post("/api/auth/users/absent/role", json={"role": "admin"})
        assert resp.status_code == 200

    def test_deactivate_user(self, auth_client) -> None:
        auth_client.post("/api/auth/register", json={"username": "grace", "password": "Secret123!"})
        resp = auth_client.post("/api/auth/users/grace/deactivate")
        assert resp.status_code == 200
        users = auth_client.get("/api/auth/users").json()
        grace = next(u for u in users if u["username"] == "grace")
        assert grace["is_active"] is False

    def test_sse_push(self, auth_client) -> None:
        resp = auth_client.post("/api/stream/push", json={"event": "test", "data": {"n": 1}})
        assert resp.status_code == 200


class TestSecurityAuditAndWorkflowRuns:
    def test_the_panel_gets_every_check_the_audit_engine_defines(self, gateway, registry, channels) -> None:
        from raven.core.security.security_audit import SecurityAudit

        expected = SecurityAudit().run_all()
        body = _make_client(gateway, registry, channels).get("/api/admin/security/audit").json()
        assert len(expected) > 10
        assert len(body["checks"]) == len(expected)
        assert {c["check"] for c in body["checks"]} == {c.name for c in expected}

    def test_a_check_is_named_the_way_the_panel_reads_it(self, gateway, registry, channels, monkeypatch) -> None:
        from raven.core.security.security_audit import AuditCheck, SecurityAudit

        def _one(self, deep: bool = False) -> list[AuditCheck]:
            check = AuditCheck("dm_policy", "Direct messages are limited", "high")
            check.fail("everyone can start a chat", fix_hint="set DM_POLICY=allowlist")
            return [check]

        monkeypatch.setattr(SecurityAudit, "run_all", _one)
        body = _make_client(gateway, registry, channels).get("/api/admin/security/audit").json()
        assert body["checks"] == [
            {
                "name": "dm_policy",
                "check": "dm_policy",
                "description": "Direct messages are limited",
                "severity": "high",
                "passed": False,
                "message": "everyone can start a chat",
                "fix_hint": "set DM_POLICY=allowlist",
            }
        ]

    def test_deep_is_the_callers_choice(self, gateway, registry, channels, monkeypatch) -> None:
        from raven.core.security.security_audit import AuditCheck, SecurityAudit

        seen: list[bool] = []

        def _spy(self, deep: bool = False) -> list[AuditCheck]:
            seen.append(deep)
            return []

        monkeypatch.setattr(SecurityAudit, "run_all", _spy)
        client = _make_client(gateway, registry, channels)
        assert client.get("/api/admin/security/audit").json() == {"checks": []}
        client.get("/api/admin/security/audit?deep=true")
        assert seen == [False, True]

    def test_runs_lists_only_tasks_that_came_from_a_template(
        self, gateway, registry, channels, tmp_path, monkeypatch
    ) -> None:
        import time

        from raven.core.config import settings
        from raven.core.task_engine.models import Task, TaskStatus
        from raven.core.task_engine.store import TaskStore

        db = tmp_path / "runs.db"
        monkeypatch.setattr(settings, "db_path", str(db))
        created = time.time() - 3600

        async def _seed() -> None:
            store = TaskStore(db)
            run = Task(id="run1", user_id="u1", channel="web", goal="report", status=TaskStatus.COMPLETED)
            run.created_at = created
            run.metadata = {"template_id": "daily-report", "template_name": "Daily report"}
            plain = Task(id="plain1", user_id="u1", channel="web", goal="ad hoc", status=TaskStatus.PENDING)
            plain.created_at = created + 60
            await store.save_task(run)
            await store.save_task(plain)
            await store.close()

        asyncio.run(_seed())
        body = _make_client(gateway, registry, channels).get("/api/admin/workflow-runs").json()
        assert [run["id"] for run in body["runs"]] == ["run1"]
        run = body["runs"][0]
        assert run["template_id"] == "daily-report"
        assert run["template_name"] == "Daily report"
        assert run["status"] == "completed"
        assert run["started_at"] == datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")

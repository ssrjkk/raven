"""The Admin screen's experimental-model endpoints.

The pull is gigabytes and minutes long, so it must not hold an HTTP request open: these tests pin the
contract the screen polls (busy, then the error left behind by the background task) and the role gate
that keeps a non-admin from starting a download.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from raven.core import heretic_model
from raven.core.admin_api import create_admin_router
from raven.core.heretic_model import SwitchResult


class _StateMiddleware:
    def __init__(self, app: ASGIApp, state: dict[str, str]) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {}).update(self.state)
        await self.app(scope, receive, send)


def _refuse_ollama(*_a: Any, **_k: Any) -> list[str]:
    raise ConnectionError("ollama is not part of this test")


@pytest.fixture
def client(request: pytest.FixtureRequest) -> Iterator[TestClient]:
    """A fresh router per test: the switch state lives in the factory closure, not in the module."""
    role = getattr(request, "param", None)
    app = FastAPI()
    app.add_middleware(_StateMiddleware, state={"user_role": role, "user_id": "tester"} if role else {})
    app.include_router(
        create_admin_router(
            lambda: {},
            lambda: SimpleNamespace(list_agents=lambda: []),
            lambda: SimpleNamespace(),
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heretic_model, "list_ollama_models", _refuse_ollama)
    monkeypatch.setattr(heretic_model, "preflight", lambda *_a, **_k: [])


class TestGet:
    def test_reports_the_model_and_that_nothing_is_running(self, client: TestClient) -> None:
        body = client.get("/api/admin/models/experimental").json()
        assert body["ref"] == heretic_model.HERETIC_HF_REF
        assert body["size_gb"] == heretic_model.HERETIC_SIZE_GB
        assert body["ollama_reachable"] is False and body["present"] is False
        assert body["busy"] is False
        assert "error" not in body, "an empty error must not be shown as a failure"

    def test_a_read_needs_no_admin_role(self, client: TestClient) -> None:
        assert client.get("/api/admin/models/experimental").status_code == 200


class TestSwitch:
    @pytest.mark.parametrize("client", ["user"], indirect=True)
    def test_a_non_admin_cannot_start_a_download(self, client: TestClient) -> None:
        assert client.post("/api/admin/models/experimental", json={"action": "enable"}).status_code == 403

    @pytest.mark.parametrize("client", [None], indirect=True)
    def test_no_role_at_all_cannot_switch(self, client: TestClient) -> None:
        assert client.post("/api/admin/models/experimental", json={"action": "enable"}).status_code == 403

    @pytest.mark.parametrize("client", ["admin"], indirect=True)
    def test_only_enable_and_disable_are_valid_actions(self, client: TestClient) -> None:
        assert client.post("/api/admin/models/experimental", json={"action": "delete"}).status_code == 422

    @pytest.mark.parametrize("client", ["admin"], indirect=True)
    def test_disable_answers_in_the_request_because_it_is_instant(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            heretic_model, "disable", lambda: SwitchResult(ok=True, detail="DEFAULT_MODEL=groq/x")
        )
        body = client.post("/api/admin/models/experimental", json={"action": "disable"}).json()
        assert body == {"ok": True, "detail": "DEFAULT_MODEL=groq/x", "busy": False}

    @pytest.mark.parametrize("client", ["admin"], indirect=True)
    def test_a_refused_disable_is_conflict_not_success(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            heretic_model,
            "disable",
            lambda: SwitchResult(ok=False, detail="nothing to restore: no key in /tmp/.env"),
        )
        res = client.post("/api/admin/models/experimental", json={"action": "disable"})
        assert res.status_code == 409
        assert "nothing to restore" in res.json()["detail"]

    @pytest.mark.parametrize("client", ["admin"], indirect=True)
    def test_enable_returns_immediately_and_the_screen_polls_for_the_outcome(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _slow_enable(_url: str, **_kw: Any) -> SwitchResult:
            time.sleep(0.2)
            return SwitchResult(ok=True, detail="DEFAULT_MODEL=ollama/heretic", pulled=True)

        monkeypatch.setattr(heretic_model, "enable", _slow_enable)

        started = client.post("/api/admin/models/experimental", json={"action": "enable"}).json()
        assert started["busy"] is True and "poll" in started["detail"]

        deadline = time.time() + 5.0
        while time.time() < deadline:
            body = client.get("/api/admin/models/experimental").json()
            if not body["busy"]:
                break
            time.sleep(0.05)
        assert body["busy"] is False, "the download task never released the switch"
        assert "error" not in body, "a successful pull must not leave an error behind"

    @pytest.mark.parametrize("client", ["admin"], indirect=True)
    def test_a_failure_in_the_background_pull_reaches_the_screen(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _failing_enable(_url: str, **_kw: Any) -> SwitchResult:
            return SwitchResult(ok=False, detail="host cannot run this model: 0.9 GB RAM free")

        monkeypatch.setattr(heretic_model, "enable", _failing_enable)
        client.post("/api/admin/models/experimental", json={"action": "enable"})

        deadline = time.time() + 5.0
        body: dict[str, Any] = {}
        while time.time() < deadline:
            body = client.get("/api/admin/models/experimental").json()
            if not body["busy"]:
                break
            time.sleep(0.05)
        assert body["busy"] is False
        assert body["error"] == "host cannot run this model: 0.9 GB RAM free"

    @pytest.mark.parametrize("client", ["admin"], indirect=True)
    def test_a_second_switch_while_one_is_running_is_refused(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _slow_enable(_url: str, **_kw: Any) -> SwitchResult:
            time.sleep(0.5)
            return SwitchResult(ok=True, detail="done")

        monkeypatch.setattr(heretic_model, "enable", _slow_enable)
        assert client.post("/api/admin/models/experimental", json={"action": "enable"}).status_code == 200
        second = client.post("/api/admin/models/experimental", json={"action": "enable"})
        assert second.status_code == 409
        assert "already running" in second.json()["detail"]

    @pytest.mark.parametrize("client", ["admin"], indirect=True)
    def test_force_is_carried_into_the_switch(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def _record(_url: str, **kwargs: Any) -> SwitchResult:
            seen.update(kwargs)
            return SwitchResult(ok=True, detail="done")

        monkeypatch.setattr(heretic_model, "enable", _record)
        client.post("/api/admin/models/experimental", json={"action": "enable", "force": True})
        deadline = time.time() + 5.0
        while time.time() < deadline and not seen:
            time.sleep(0.05)
        assert seen == {"pull": True, "force": True}

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.project_insights_api as pia


def test_count_reverts() -> None:
    commits: list[dict[str, Any]] = [
        {"message": "Add feature"},
        {"message": "Revert broken change"},
        {"message": "revert 0abc"},
        {"message": ""},
    ]
    assert pia._count_reverts(commits) == 2


def _commit(day: str | None, message: str) -> dict[str, Any]:
    return {"date": day, "message": message}


def test_compute_project_insights_basic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        pia, "_scan_code_stats", lambda ws: {"py": {"code": 1000, "files": 3}, "js": {"code": 500, "files": 2}}
    )
    today = datetime.now(UTC).date()
    day1 = (today - timedelta(days=1)).isoformat()
    day2 = (today - timedelta(days=2)).isoformat()
    commits = [
        _commit(day1, "feat: x"),
        _commit(day1, "fix: y"),
        _commit(day2, "Revert bad change"),
    ]
    result = pia.compute_project_insights("proj-1", tmp_path, commits, days=5)
    assert result["project_id"] == "proj-1"
    assert result["files"] == 5
    assert result["code_lines"] == 1500
    assert result["commits"] == 3
    assert result["active_days"] == 2
    assert result["success_rate"] == pytest.approx(100.0 * (1.0 - 1 / 3), abs=0.1)
    assert len(result["trend"]) == 5
    assert result["trend"][-1]["date"] == today.isoformat()
    assert result["trend"][-1]["commits"] == 0
    assert result["trend"][-2]["date"] == day1
    assert result["trend"][-2]["commits"] == 2
    assert result["trend"][-3]["date"] == day2
    assert result["trend"][-3]["commits"] == 1
    assert result["trend"][0]["commits"] == 0
    assert result["time_saved_minutes"] >= 0
    assert result["ai_contribution_percent"] >= 0.0
    assert result["token_cost_estimate"] >= 0.0
    assert result["generated_at"]


def test_compute_project_insights_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pia, "_scan_code_stats", lambda ws: {})
    result = pia.compute_project_insights("proj-2", tmp_path, [], days=3)
    assert result["commits"] == 0
    assert result["active_days"] == 0
    assert result["success_rate"] == 100.0
    assert result["ai_contribution_percent"] == 0.0
    assert len(result["trend"]) == 3
    assert all(p["commits"] == 0 for p in result["trend"])


def test_compute_project_insights_dates_without_year(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pia, "_scan_code_stats", lambda ws: {"py": {"code": 1, "files": 1}})
    commits = [_commit("", "msg"), _commit(None, "msg2")]
    result = pia.compute_project_insights("proj-3", tmp_path, commits, days=2)
    assert result["commits"] == 2
    assert result["active_days"] == 1


def test_project_insights_endpoint_no_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pia, "_get_git", lambda ws: None)
    monkeypatch.setattr(pia, "_scan_code_stats", lambda ws: {})
    app = FastAPI()
    app.include_router(pia.create_project_insights_router(str(tmp_path)))
    c = TestClient(app)
    resp = c.get("/api/v1/projects/abc/insights", params={"days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == "abc"
    assert body["commits"] == 0
    assert len(body["trend"]) == 7


def test_project_insights_endpoint_with_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_git = SimpleNamespace(_run=lambda *a: ("", ""))

    async def fake_log(git: object, days: int) -> str:
        return "abc|abc|feat one|A|a@x.com|2026-08-01|2026-08-01T10:00:00|HEAD\n3\t2\tf.py\n"

    monkeypatch.setattr(pia, "_get_git", lambda ws: fake_git)
    monkeypatch.setattr(pia, "_get_git_log_async", fake_log)
    monkeypatch.setattr(pia, "_scan_code_stats", lambda ws: {"py": {"code": 500, "files": 2}})
    app = FastAPI()
    app.include_router(pia.create_project_insights_router(str(tmp_path)))
    c = TestClient(app)
    resp = c.get("/api/v1/projects/abc/insights", params={"days": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["commits"] == 1
    assert body["active_days"] == 1
    assert body["files"] == 2


def test_project_insights_endpoint_git_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_git = SimpleNamespace(_run=lambda *a: ("", ""))

    async def boom(git: object, days: int) -> str:
        raise RuntimeError("scan boom")

    monkeypatch.setattr(pia, "_get_git", lambda ws: fake_git)
    monkeypatch.setattr(pia, "_get_git_log_async", boom)
    monkeypatch.setattr(pia, "_scan_code_stats", lambda ws: {})
    app = FastAPI()
    app.include_router(pia.create_project_insights_router(str(tmp_path)))
    c = TestClient(app)
    resp = c.get("/api/v1/projects/abc/insights")
    assert resp.status_code == 200
    assert resp.json()["commits"] == 0

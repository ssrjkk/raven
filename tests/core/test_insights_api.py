from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.insights_api as ia
from raven.coding.git_integration import GitIntegration

SAMPLE_LOG = (
    "abc123|abc|first commit|Alice|alice@x.com|2026-08-01|2026-08-01T10:00:00|HEAD -> main\n"
    "3\t2\tfile1.py\n"
    "0\t1\tfile2.py\n"
    "def456|def|second commit|Bob|bob@x.com|2026-08-02|bad-date|refs\n"
    "-\t-\tfile3.py\n"
)


def _git(r: Path, *args: str) -> tuple[str, str]:
    p = subprocess.run(["git", "-C", str(r), *args], capture_output=True, text=True)
    return p.stdout.strip(), p.stderr.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@t.com")
    _git(r, "config", "user.name", "T")
    (r / "a.txt").write_text("x\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    return r


def _client(workspace: str) -> TestClient:
    app = FastAPI()
    app.include_router(ia.create_insights_router(workspace))
    return TestClient(app)


def test_coding_no_repo(tmp_path: Path) -> None:
    c = _client(str(tmp_path / "empty"))
    resp = c.get("/api/insights/coding")
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] == "no git repo found"
    assert body["commits_per_day"] == []


def test_coding_get_git_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: GitIntegration) -> bool:
        raise RuntimeError("is_repo boom")

    monkeypatch.setattr(GitIntegration, "is_repo", boom)
    c = _client(str(tmp_path / "ws"))
    resp = c.get("/api/insights/coding")
    assert resp.status_code == 200
    assert resp.json()["error"] == "no git repo found"


def test_coding_empty_log(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = GitIntegration._run

    def fake_run(self: GitIntegration, *args: str) -> tuple[str, str]:
        if args and args[0] == "rev-parse":
            return real(self, *args)
        return "", ""

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    c = _client(str(git_repo))
    resp = c.get("/api/insights/coding")
    assert resp.status_code == 200
    body = resp.json()
    assert body["commits_per_day"] == []
    assert body["top_files"] == []
    assert body["peak_hours"] == []


def test_coding_success(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = GitIntegration._run

    def fake_run(self: GitIntegration, *args: str) -> tuple[str, str]:
        if args and args[0] == "rev-parse":
            return real(self, *args)
        return SAMPLE_LOG, ""

    monkeypatch.setattr(GitIntegration, "_run", fake_run)
    c = _client(str(git_repo))
    resp = c.get("/api/insights/coding", params={"days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_commits"] == 2
    assert body["total_days_active"] == 2
    assert body["avg_commits_per_day"] == 1.0
    assert body["commits_per_day"] == [
        {"date": "2026-08-01", "count": 1},
        {"date": "2026-08-02", "count": 1},
    ]
    assert {"hour": 10, "count": 1} in body["peak_hours"]
    paths = [f["path"] for f in body["top_files"]]
    assert paths == ["file1.py", "file2.py", "file3.py"]
    changes = {f["path"]: f["changes"] for f in body["top_files"]}
    assert changes["file1.py"] == 5
    assert changes["file2.py"] == 1


def test_get_git_log_async_ok() -> None:
    git = SimpleNamespace(_run=lambda *a: ("out", "err"))
    assert asyncio.run(ia._get_git_log_async(git, 30)) == "out"


def test_get_git_log_async_timeout() -> None:
    def boom(*args: str) -> tuple[str, str]:
        raise TimeoutError

    git = SimpleNamespace(_run=boom)
    assert asyncio.run(ia._get_git_log_async(git, 30)) == ""


def test_get_git_log_async_error() -> None:
    def boom(*args: str) -> tuple[str, str]:
        raise RuntimeError("git boom")

    git = SimpleNamespace(_run=boom)
    assert asyncio.run(ia._get_git_log_async(git, 30)) == ""


def test_llm_insights_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ia, "_cost", SimpleNamespace(_records=[]))
    c = _client(str(tmp_path))
    resp = c.get("/api/insights/llm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_calls"] == 0
    assert body["total_cost"] == 0
    assert body["models"] == []


def _rec(ts: float, model: str, cost: float, itok: int, otok: int) -> SimpleNamespace:
    return SimpleNamespace(timestamp=ts, model=model, cost=cost, input_tokens=itok, output_tokens=otok)


def test_llm_insights_aggregation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    today = datetime.now(tz=UTC)
    yesterday = today.timestamp() - 86400
    records = [
        _rec(today.timestamp(), "gpt-4o", 0.5, 100, 50),
        _rec(today.timestamp(), "gpt-4o", 0.25, 50, 50),
        _rec(yesterday, "claude-3", 0.1, 10, 5),
        _rec(yesterday - 10 * 86400, "gpt-4o", 0.2, 10, 10),
    ]
    monkeypatch.setattr(ia, "_cost", SimpleNamespace(_records=records))
    c = _client(str(tmp_path))
    resp = c.get("/api/insights/llm", params={"days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_calls"] == 3
    assert body["total_tokens"] == 150 + 100 + 15
    assert round(body["total_cost"], 4) == 0.85
    models = {m["model"]: m["calls"] for m in body["models"]}
    assert models == {"gpt-4o": 2, "claude-3": 1}
    assert len(body["calls_per_day"]) == 2
    assert len(body["peak_hours"]) >= 1


def test_workspace_insights(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "main.py").write_text("print(1)\n", encoding="utf-8")
    (ws / "README").write_text("hi", encoding="utf-8")
    (ws / ".hidden").write_text("nope", encoding="utf-8")
    sub = ws / "sub"
    sub.mkdir()
    (sub / "util.js").write_text("const x = 1;\n", encoding="utf-8")
    c = _client(str(ws))
    resp = c.get("/api/insights/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_files"] == 3
    assert body["total_dirs"] == 1
    assert body["by_extension"][".py"] == 1
    assert body["by_extension"][".js"] == 1
    assert body["by_extension"]["(no ext)"] == 1
    largest = {f["path"]: f["size_bytes"] for f in body["largest_files"]}
    assert largest["main.py"] >= 9
    assert ".hidden" not in largest


def test_parse_log_units() -> None:
    parsed = ia._parse_log(SAMPLE_LOG)
    assert len(parsed) == 2
    assert parsed[0]["hash"] == "abc"
    assert parsed[0]["message"] == "first commit"
    assert parsed[0]["author"] == "Alice"
    assert parsed[0]["files"] == [
        {"path": "file1.py", "added": 3, "deleted": 2},
        {"path": "file2.py", "added": 0, "deleted": 1},
    ]
    assert parsed[1]["files"] == [{"path": "file3.py", "added": 0, "deleted": 0}]


def test_parse_log_empty() -> None:
    assert ia._parse_log("") == []


def test_parse_log_bad_numstat() -> None:
    raw = "abc|a|msg|au|ae|2026-01-01|2026-01-01T00:00:00|\nzz\t2\tfile.py\n"
    parsed = ia._parse_log(raw)
    assert len(parsed) == 1
    assert parsed[0]["files"] == [{"path": "file.py", "added": 0, "deleted": 0}]

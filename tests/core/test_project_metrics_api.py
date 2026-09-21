from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.project_metrics_api import _count_lines, create_project_metrics_router


@pytest.fixture()
def client():
    router = create_project_metrics_router()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestCountLines:
    def test_python_file(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("# comment\nx = 1\n\ny = 2\n")
        lines, code = _count_lines(f)
        assert lines == 4
        assert code == 2

    def test_js_file(self, tmp_path):
        f = tmp_path / "test.js"
        f.write_text("// comment\nconst x = 1;\n/* block */\nconst y = 2;\n")
        lines, code = _count_lines(f)
        assert lines == 4
        assert code == 2

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        lines, code = _count_lines(f)
        assert lines == 0
        assert code == 0

    def test_missing_file(self, tmp_path):
        f = tmp_path / "missing.py"
        lines, code = _count_lines(f)
        assert lines == 0
        assert code == 0


class TestProjectMetrics:
    def test_empty_workspace(self, client, tmp_path):
        with patch("raven.core.project_metrics_api._get_workspace", return_value=tmp_path):
            resp = client.get("/api/metrics/project")
        assert resp.status_code == 200
        data = resp.json()
        assert "code_stats" in data
        assert "summary" in data
        assert "dependencies" in data
        assert "activity" in data

    def test_workspace_with_files(self, client, tmp_path):
        (tmp_path / "test.py").write_text("x = 1\ny = 2\n")
        (tmp_path / "app.ts").write_text("const x = 1;\n")
        with patch("raven.core.project_metrics_api._get_workspace", return_value=tmp_path):
            resp = client.get("/api/metrics/project")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_files"] >= 2
        assert data["summary"]["total_lines"] >= 3

    def test_nonexistent_workspace(self, client, tmp_path):
        missing = tmp_path / "nonexistent"
        with patch("raven.core.project_metrics_api._get_workspace", return_value=missing):
            resp = client.get("/api/metrics/project")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_files"] == 0

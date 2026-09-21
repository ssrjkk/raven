from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.tests_api import create_tests_router


class TestTestsApi:
    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(create_tests_router())
        return TestClient(app)

    def test_tests_run_endpoint(self, client):
        with patch("raven.tools.tests.run_tests", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Test output"
            response = client.post(
                "/api/tests/run",
                json={"path": "tests/", "marker": "", "timeout": 120, "extra_args": ""},
            )
            assert response.status_code == 200
            assert response.json() == {"text": "Test output"}
            mock_run.assert_called_once()

    def test_tests_run_with_defaults(self, client):
        with patch("raven.tools.tests.run_tests", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Output"
            response = client.post("/api/tests/run", json={})
            assert response.status_code == 200
            mock_run.assert_called_once_with(path="", marker="", timeout=120, extra_args="")

    def test_tests_coverage_endpoint(self, client):
        with patch("raven.tools.tests.test_coverage", new_callable=AsyncMock) as mock_cov:
            mock_cov.return_value = "Coverage report"
            response = client.post(
                "/api/tests/coverage",
                json={"path": "raven/", "timeout": 180},
            )
            assert response.status_code == 200
            assert response.json() == {"text": "Coverage report"}
            mock_cov.assert_called_once()

    def test_tests_coverage_with_defaults(self, client):
        with patch("raven.tools.tests.test_coverage", new_callable=AsyncMock) as mock_cov:
            mock_cov.return_value = "Report"
            response = client.post("/api/tests/coverage", json={})
            assert response.status_code == 200
            mock_cov.assert_called_once_with(path="", timeout=180)

    def test_tests_generate_endpoint(self, client):
        with patch("raven.tools.tests.generate_tests", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Generated tests"
            response = client.post(
                "/api/tests/generate",
                json={"file_path": "raven/core/example.py"},
            )
            assert response.status_code == 200
            assert response.json() == {"text": "Generated tests"}
            mock_gen.assert_called_once()

    def test_tests_generate_with_defaults(self, client):
        with patch("raven.tools.tests.generate_tests", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Tests"
            response = client.post("/api/tests/generate", json={})
            assert response.status_code == 200
            mock_gen.assert_called_once_with(file_path="")

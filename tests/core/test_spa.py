from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.spa import mount_spa


class TestMountSpa:
    def test_returns_false_when_dist_not_exists(self, tmp_path: Path):
        app = FastAPI()
        missing_dir = tmp_path / "nonexistent"
        result = mount_spa(app, missing_dir)
        assert result is False

    def test_returns_true_when_dist_exists(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html></html>")

        result = mount_spa(app, web_dist)
        assert result is True

    def test_mounts_assets_when_present(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        assets = web_dist / "assets"
        assets.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html></html>")

        result = mount_spa(app, web_dist)
        assert result is True

    def test_spa_fallback_returns_index(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html><body>Test</body></html>")

        mount_spa(app, web_dist)
        client = TestClient(app)

        response = client.get("/some/route")
        assert response.status_code == 200
        assert "Test" in response.text

    def test_spa_fallback_rejects_api_paths(self, tmp_path: Path):
        app = FastAPI()
        web_dist = tmp_path / "dist"
        web_dist.mkdir()
        index = web_dist / "index.html"
        index.write_text("<html></html>")

        mount_spa(app, web_dist)
        client = TestClient(app)

        response = client.get("/api/something")
        assert response.status_code == 404

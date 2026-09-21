from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.browser_api import create_browser_router


@pytest.fixture()
def mock_agent():
    agent = AsyncMock()
    agent._started = True
    agent.page = MagicMock()
    agent.page.url = "https://example.com"
    agent.navigate = AsyncMock(return_value="Page loaded")
    agent.get_title = AsyncMock(return_value="Example")
    agent.click = AsyncMock(return_value=True)
    agent.fill = AsyncMock(return_value=True)
    agent.type_text = AsyncMock(return_value=True)
    agent.fill_form = AsyncMock(return_value=True)
    agent.select_option = AsyncMock(return_value=True)
    agent.screenshot = AsyncMock(return_value="base64data")
    agent.evaluate = AsyncMock(return_value="result")
    agent.get_text = AsyncMock(return_value="Hello")
    agent.get_html = AsyncMock(return_value="<p>Hello</p>")
    agent.wait_for_selector = AsyncMock(return_value=True)
    agent.wait_for_function = AsyncMock(return_value=True)
    agent.wait_for_navigation = AsyncMock(return_value=True)
    agent.scroll = AsyncMock(return_value=True)
    agent.get_cookies = AsyncMock(return_value=[])
    agent.set_cookies = AsyncMock(return_value=True)
    agent.clear_cookies = AsyncMock(return_value=True)
    agent.start_network_intercept = AsyncMock(return_value=True)
    agent.stop_network_intercept = AsyncMock(return_value=True)
    agent.get_intercepted_requests = AsyncMock(return_value=[])
    agent.get_intercepted_responses = AsyncMock(return_value=[])
    agent.new_tab = AsyncMock(return_value=True)
    agent.list_tabs = AsyncMock(return_value=[])
    agent.switch_tab = AsyncMock(return_value=True)
    agent.close_tab = AsyncMock(return_value=True)
    agent.extract_table = AsyncMock(return_value=[])
    agent.set_extra_http_headers = AsyncMock(return_value=True)
    agent.set_download_handler = AsyncMock(return_value=True)
    agent.get_download = AsyncMock(return_value="file.bin")
    agent.get_title = AsyncMock(return_value="Title")
    agent.extract_content = AsyncMock(return_value="Content")
    agent.screenshot_bytes = AsyncMock(return_value=b"pngdata")
    return agent


@pytest.fixture()
def client(mock_agent):
    import raven.core.browser_api as browser_mod
    original_agent = browser_mod._agent
    browser_mod._agent = mock_agent
    try:
        with patch("raven.core.browser_api._stop_agent", new_callable=AsyncMock):
            router = create_browser_router()
            app = FastAPI()
            app.include_router(router)
            yield TestClient(app)
    finally:
        browser_mod._agent = original_agent


class TestBrowserBasic:
    def test_start(self, client):
        resp = client.post("/api/browser/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_stop(self, client):
        resp = client.post("/api/browser/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_status(self, client, mock_agent):
        resp = client.get("/api/browser/status")
        assert resp.status_code == 200
        assert resp.json()["started"] is True


class TestBrowserActions:
    def test_navigate(self, client, mock_agent):
        with patch("raven.core.security.ssrf.validate_url", return_value=None):
            resp = client.post("/api/browser/navigate", json={"url": "https://example.com"})
        assert resp.status_code == 200
        assert "text" in resp.json()

    def test_click(self, client):
        resp = client.post("/api/browser/click", json={"selector": "#btn"})
        assert resp.status_code == 200
        assert resp.json()["result"] is True

    def test_fill(self, client):
        resp = client.post("/api/browser/fill", json={"selector": "#input", "value": "test"})
        assert resp.status_code == 200

    def test_type(self, client):
        resp = client.post("/api/browser/type", json={"selector": "#input", "text": "hello"})
        assert resp.status_code == 200

    def test_screenshot(self, client):
        resp = client.post("/api/browser/screenshot", json={})
        assert resp.status_code == 200

    def test_evaluate(self, client):
        resp = client.post("/api/browser/evaluate", json={"script": "1+1"})
        assert resp.status_code == 200

    def test_get_text(self, client):
        resp = client.post("/api/browser/text", json={"selector": "body"})
        assert resp.status_code == 200
        assert resp.json()["text"] == "Hello"

    def test_get_html(self, client):
        resp = client.post("/api/browser/html", json={"selector": "body"})
        assert resp.status_code == 200
        assert "<p>" in resp.json()["html"]


class TestBrowserTabs:
    def test_new_tab(self, client):
        resp = client.post("/api/browser/tabs", json={"url": "https://example.com"})
        assert resp.status_code == 200

    def test_list_tabs(self, client):
        resp = client.get("/api/browser/tabs")
        assert resp.status_code == 200

    def test_switch_tab(self, client):
        resp = client.post("/api/browser/tabs/switch", json={"index": 0})
        assert resp.status_code == 200

    def test_close_tab(self, client):
        resp = client.post("/api/browser/tabs/close", json={})
        assert resp.status_code == 200


class TestBrowserCookies:
    def test_get_cookies(self, client):
        resp = client.get("/api/browser/cookies")
        assert resp.status_code == 200

    def test_set_cookies(self, client):
        resp = client.post("/api/browser/cookies", json={"cookies": [{"name": "a", "value": "b"}]})
        assert resp.status_code == 200

    def test_clear_cookies(self, client):
        resp = client.delete("/api/browser/cookies")
        assert resp.status_code == 200


class TestBrowserMisc:
    def test_scroll(self, client):
        resp = client.post("/api/browser/scroll", json={"direction": "down", "amount": 500})
        assert resp.status_code == 200

    def test_get_title(self, client):
        resp = client.get("/api/browser/title")
        assert resp.status_code == 200

    def test_get_url(self, client, mock_agent):
        resp = client.get("/api/browser/url")
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://example.com"

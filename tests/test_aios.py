from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from aios.api.bridge import router
from aios.agents.orchestrator import AgentType, Orchestrator


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestAiosBridge:
    def test_health(self, client):
        resp = client.get("/aios/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["module"] == "ai-os-mvp"

    @patch("aios.api.bridge.LLMRouter")
    def test_ai_gateway_success(self, mock_llm_cls, client):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Hello from AI"
        mock_llm.complete = AsyncMock(return_value=mock_response)
        mock_llm_cls.return_value = mock_llm

        resp = client.post("/aios/ai", json={"prompt": "test", "task": "code"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Hello from AI"
        assert data["provider"] == "openrouter"

    @patch("aios.api.bridge.LLMRouter")
    def test_ai_gateway_architecture_task(self, mock_llm_cls, client):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Architecture plan"
        mock_llm.complete = AsyncMock(return_value=mock_response)
        mock_llm_cls.return_value = mock_llm

        resp = client.post("/aios/ai", json={"prompt": "design", "task": "architecture"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "anthropic"


class TestAiosOrchestrator:
    @pytest.mark.asyncio
    async def test_dispatch_unknown_agent(self):
        orch = Orchestrator()
        result = await orch.dispatch("task", AgentType.PLANNER)
        assert "agent" in result

    @pytest.mark.asyncio
    async def test_autonomous_loop_structure(self):
        orch = Orchestrator()
        result = await orch.dispatch("test", AgentType.AUTONOMOUS)
        assert isinstance(result, dict)
        assert result.get("agent") == "autonomous"

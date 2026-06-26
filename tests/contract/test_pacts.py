"""Pact contract tests for Raven microservices.

Tests API compatibility between consumer and provider services.
Run: pytest tests/contract/ --pact-provider=<name>
"""

import os
from pathlib import Path

import pytest
from pact import Consumer, Like, Provider, Term

PACT_DIR = Path("tests/contract/pacts")
PACT_DIR.mkdir(parents=True, exist_ok=True)

PACT_BROKER_URL = os.environ.get("PACT_BROKER_URL", "")
PACT_BROKER_TOKEN = os.environ.get("PACT_BROKER_TOKEN", "")
PACT_PUBLISH = os.environ.get("PACT_PUBLISH", "false").lower() == "true"


@pytest.fixture
def pact_dir():
    return PACT_DIR


class TestGatewayAuthContract:
    """Gateway (consumer) ← Auth (provider) contract."""

    def test_health_check(self, pact_dir):
        pact = Consumer("gateway").has_pact_with(
            Provider("auth"),
            pact_dir=str(pact_dir),
            version="1.0.0",
        )
        expected = {"status": "healthy", "service": "auth"}
        (
            pact.given("auth service is running")
            .upon_receiving("a health check request")
            .with_request("GET", "/health")
            .will_respond_with(200, body=Like(expected))
        )

        with pact:
            import httpx

            result = httpx.get("http://localhost:8001/health")
            assert result.status_code == 200
            assert result.json()["service"] == "auth"

    def test_validate_token(self, pact_dir):
        pact = Consumer("gateway").has_pact_with(
            Provider("auth"),
            pact_dir=str(pact_dir),
        )
        token = Term(r"^[A-Za-z0-9\-_.]+\.[A-Za-z0-9\-_.]+\.[A-Za-z0-9\-_.]+$", "valid.jwt.token")
        expected = {"valid": True, "user_id": "user-123", "role": "admin"}
        (
            pact.given("a valid JWT token exists")
            .upon_receiving("a token validation request")
            .with_request("POST", "/api/v1/auth/validate", body={"token": token})
            .will_respond_with(200, body=Like(expected))
        )

        with pact:
            import httpx

            result = httpx.post("http://localhost:8001/api/v1/auth/validate", json={"token": "valid.jwt.token"})
            assert result.status_code == 200
            assert result.json()["valid"] is True


class TestGatewayAgentContract:
    """Gateway (consumer) ← Agent (provider) contract."""

    def test_run_agent(self, pact_dir):
        pact = Consumer("gateway").has_pact_with(
            Provider("agent-core"),
            pact_dir=str(pact_dir),
        )
        request_body = {"session_id": "sess-1", "message": "Hello"}
        expected = {"response": "Hi there!", "session_id": "sess-1"}
        (
            pact.given("agent-core is ready")
            .upon_receiving("a message for processing")
            .with_request("POST", "/api/v1/agent/chat", body=Like(request_body))
            .will_respond_with(200, body=Like(expected))
        )

        with pact:
            import httpx

            result = httpx.post("http://localhost:8002/api/v1/agent/chat", json=request_body)
            assert result.status_code == 200

from __future__ import annotations

import os
import time
from typing import Any

from loguru import logger
from pydantic import SecretStr

from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.llm.providers.base import _parse_openai_response, _stream_sse

_TOKEN_TTL = 1500.0


class CopilotProvider(LLMProvider):
    def __init__(self, **overrides):
        import httpx

        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )
        raw = overrides.get("api_key") or os.environ.get("COPILOT_TOKEN") or ""
        self._token: SecretStr | None = SecretStr(raw) if raw else None
        self._static = bool(raw)
        self._token_expires_at: float = 0.0
        self._github_token = os.environ.get("GITHUB_TOKEN", "")

    async def _get_token(self) -> str:
        if self._token and (self._static or time.monotonic() < self._token_expires_at):
            return self._token.get_secret_value()
        if not self._github_token:
            logger.warning("No GITHUB_TOKEN or COPILOT_TOKEN set for CopilotProvider")
            return ""
        try:
            resp = await self.http.post(
                "https://api.github.com/copilot_internal/v2/token",
                headers={"Authorization": f"Bearer {self._github_token}", "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("token", self._github_token)
            self._token = SecretStr(raw) if raw else None
            self._token_expires_at = time.monotonic() + _TOKEN_TTL
        except Exception as e:
            logger.warning("Failed to get Copilot token: {}", e)
            raw = self._github_token
            self._token = SecretStr(raw) if raw else None
            self._token_expires_at = 0.0
        return self._token.get_secret_value() if self._token else ""

    async def cleanup(self):
        await self.http.aclose()
        self._token = None

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        model_name = model.replace("copilot/", "")
        body = {"model": model_name, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token_str in _stream_sse(self.http, "https://api.githubcopilot.com/chat/completions", body, headers):
            yield token_str

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        model_name = model.replace("copilot/", "")
        body = {"model": model_name, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post("https://api.githubcopilot.com/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        return _parse_openai_response(resp.json())

from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger
from pydantic import SecretStr

from raven.core._json import json
from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.llm.providers.base import _convert_to_gemini, _read_json_file


class VertexAIProvider(LLMProvider):
    def __init__(self, **overrides):
        self.project = overrides.get("project") or os.environ.get("VERTEX_AI_PROJECT", "")
        self.location = overrides.get("location") or os.environ.get("VERTEX_AI_LOCATION", "us-central1")
        import httpx
        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )
        raw = overrides.get("api_key") or ""
        self._api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self._token: str | None = None

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        try:
            proc = await asyncio.create_subprocess_exec(
                "gcloud", "auth", "print-access-token",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except TimeoutError:
                proc.kill()
                logger.warning("gcloud auth timed out after 30s")
                raise
            if proc.returncode == 0:
                self._token = stdout.decode().strip()
                return self._token
            err_text = stderr.decode().strip()
            logger.warning("gcloud auth failed (rc={}): {}", proc.returncode, err_text)
        except FileNotFoundError:
            logger.debug("gcloud not found, trying credentials file")
        creds_path = os.environ.get("VERTEX_AI_CREDENTIALS") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if creds_path:
            loop = asyncio.get_running_loop()
            try:
                creds = await loop.run_in_executor(None, _read_json_file, creds_path)
            except (FileNotFoundError, ValueError) as e:
                logger.warning("Vertex AI: failed to read credentials file: {}", e)
                return ""
            self._token = creds.get("access_token", "")
            if not self._token and "private_key" in creds:
                logger.warning("Vertex AI: service account needs `gcloud auth application-default print-access-token`")
        return self._token or ""

    async def cleanup(self):
        await self.http.aclose()

    def _model_id(self, model: str) -> str:
        return model.replace("vertex/", "").replace("gemini/", "")

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        token = await self._get_token()
        model_id = self._model_id(model)
        url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}/locations/{self.location}/publishers/google/models/{model_id}:streamGenerateContent"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        gemini_messages = _convert_to_gemini(messages)
        body = {"contents": gemini_messages}
        async with self.http.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    try:
                        chunk = json.loads(line)
                        for c in chunk.get("candidates", []):
                            content = c.get("content", {}).get("parts", [{}])[0].get("text", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        token = await self._get_token()
        model_id = self._model_id(model)
        url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}/locations/{self.location}/publishers/google/models/{model_id}:generateContent"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        gemini_messages = _convert_to_gemini(messages)
        body = {"contents": gemini_messages}
        resp = await self.http.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        text = ""
        for c in data.get("candidates", []):
            for part in c.get("content", {}).get("parts", []):
                text += part.get("text", "")
        return LLMResponse(content=text, finish_reason="stop")

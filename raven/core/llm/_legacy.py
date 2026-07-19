from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
import os
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from loguru import logger
from pydantic import SecretStr

from raven.core._json import json
from raven.core.cache.llm_cache import LLMCache
from raven.core.config import settings
from raven.core.failover import ModelFailover
from raven.core.llm.protocol import LLMProvider, LLMResponse, ToolCall
from raven.core.metrics import InstrumentedLLMProvider, metrics
from raven.core.tracing import trace_llm_call


def _parse_retry_after(headers: Any, default: int = 5) -> int:
    raw = headers.get("Retry-After")
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        pass
    try:
        parsed = datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %Z")
        return max(int(parsed.timestamp() - time.time()), 0)
    except (ValueError, TypeError):
        return default


def _read_json_file(path: str) -> dict[str, Any]:
    with open(path) as f:
        import json as _json
        data = _json.load(f)
        return cast("dict[str, Any]", data)


async def _stream_sse(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, Any],
    done_marker: str = "[DONE]",
    data_prefix: str = "data: ",
    extract_token: Callable[[dict[str, Any]], str] = lambda c: (
        c.get("choices", [{}])[0].get("delta", {}).get("content", "")
    ),
) -> AsyncIterator[str]:
    async with client.stream("POST", url, json=body, headers=headers) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith(data_prefix):
                data = line[len(data_prefix) :]
                if data.strip() == done_marker:
                    break
                try:
                    chunk = json.loads(data)
                    token = extract_token(chunk)
                    if token:
                        yield token
                except json.JSONDecodeError:
                    continue


def _parse_openai_response(data: dict[str, Any]) -> LLMResponse:
    choice = data.get("choices", [{}])[0] if data.get("choices") else {}
    msg = choice.get("message", {}) if isinstance(choice, dict) else {}
    content = msg.get("content", "") or ""
    tool_calls_raw = msg.get("tool_calls")
    tool_calls = [ToolCall.from_openai(tc) for tc in tool_calls_raw] if tool_calls_raw else []
    return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=choice.get("finish_reason", "stop"))


class BaseLLMProvider:
    """Base class for LLM providers with SecretStr API key handling."""

    def __init__(self, api_key: SecretStr | str, base_url: str, timeout: float = 120.0):
        self._api_key = SecretStr(api_key) if isinstance(api_key, str) else api_key
        self.http = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()
        self._api_key = SecretStr("")

    def _get_api_key(self) -> str:
        return self._api_key.get_secret_value()


class OpenRouterProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or settings.openrouter_api_key.get_secret_value()
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.base_url = overrides.get("base_url") or "https://openrouter.ai/api/v1"
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    async def _headers(self) -> dict[str, Any]:
        return {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/raven-ai",
            "X-Title": "Raven AI",
        }

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        body = {"model": model.replace("openrouter/", ""), "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token in _stream_sse(self.http, f"{self.base_url}/chat/completions", body, await self._headers()):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        model_name = model.replace("openrouter/", "")
        body = {"model": model_name, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(f"{self.base_url}/chat/completions", json=body, headers=await self._headers())
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class OpenAIProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or settings.openai_api_key.get_secret_value()
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.base_url = overrides.get("base_url") or "https://api.openai.com/v1"
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        body = {"model": model, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token in _stream_sse(
            self.http,
            f"{self.base_url}/chat/completions",
            body,
            {
                "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        ):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        body = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class AnthropicProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or settings.anthropic_api_key.get_secret_value()
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.base_url = overrides.get("base_url") or "https://api.anthropic.com"
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    def _build_body(
        self, messages: list[dict[str, Any]], model: str, stream: bool, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        body = {
            "model": model,
            "messages": [m for m in messages if m["role"] != "system"],
            "system": "\n\n".join(m["content"] for m in messages if m["role"] == "system"),
            "max_tokens": 4096,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
        return body

    def _headers(self) -> dict[str, Any]:
        return {"x-api-key": self.api_key.get_secret_value(), "anthropic-version": "2023-06-01", "Content-Type": "application/json"}

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        body = self._build_body(messages, model, True, tools)
        async for token in _stream_sse(
            self.http,
            f"{self.base_url}/v1/messages",
            body,
            self._headers(),
            done_marker="",
            extract_token=lambda c: (
                c.get("delta", {}).get("text", "") if c.get("type") == "content_block_delta" else ""
            ),
        ):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        body = self._build_body(messages, model, False, tools)
        resp = await self.http.post(f"{self.base_url}/v1/messages", json=body, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        tool_calls_raw = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
        tool_calls = []
        for tc in tool_calls_raw:
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=tc.get("input", {}),
                )
            )
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason="stop")


class OllamaProvider(LLMProvider):
    def __init__(self, **overrides):
        self.base_url = overrides.get("base_url") or settings.ollama_base_url
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        model_name = model.replace("ollama/", "")
        body = {"model": model_name, "messages": messages, "stream": True}
        async with self.http.stream("POST", f"{self.base_url}/api/chat", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    try:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        model_name = model.replace("ollama/", "")
        body = {"model": model_name, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(f"{self.base_url}/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        tool_calls_raw = data.get("message", {}).get("tool_calls", [])
        tool_calls = []
        for tc in tool_calls_raw:
            func = tc.get("function", tc)
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=func.get("arguments", {}),
                )
            )
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason="stop")


class VLLMProvider(LLMProvider):
    """vLLM — OpenAI-compatible API, runs on RunPod / self-hosted GPU."""
    def __init__(self, **overrides):
        self.base_url = overrides.get("base_url") or settings.vllm_base_url
        raw = overrides.get("api_key") or ""
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        body = {"model": model.replace("vllm/", ""), "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        async for token in _stream_sse(self.http, f"{self.base_url}/v1/chat/completions", body, headers):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        body = {"model": model.replace("vllm/", ""), "messages": messages}
        if tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        resp = await self.http.post(f"{self.base_url}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class AzureProvider(LLMProvider):
    """Azure OpenAI — OpenAI-compatible API via Azure."""
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.endpoint = overrides.get("base_url") or os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com")
        self.api_version = overrides.get("api_version") or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    def _deployment(self, model: str) -> str:
        return model.replace("azure/", "")

    def _url(self, deployment: str) -> str:
        return f"{self.endpoint}/openai/deployments/{deployment}/chat/completions?api-version={self.api_version}"

    async def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "api-key": self.api_key.get_secret_value()}

    async def complete_stream(self, messages, model, tools=None):
        deployment = self._deployment(model)
        body = {"messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token in _stream_sse(self.http, self._url(deployment), body, await self._headers()):
            yield token

    async def complete(self, messages, model, tools=None):
        deployment = self._deployment(model)
        body = {"messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(self._url(deployment), json=body, headers=await self._headers())
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class CopilotProvider(LLMProvider):
    """GitHub Copilot — uses GitHub OAuth token for OpenAI-compatible API."""
    def __init__(self, **overrides):
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))
        raw = overrides.get("api_key") or os.environ.get("COPILOT_TOKEN") or ""
        self._token: SecretStr | None = SecretStr(raw) if raw else None
        self._github_token = os.environ.get("GITHUB_TOKEN", "")

    async def _get_token(self) -> str:
        if self._token:
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
        except Exception as e:
            logger.warning("Failed to get Copilot token: {}", e)
            raw = self._github_token
            self._token = SecretStr(raw) if raw else None
        return self._token.get_secret_value() if self._token else ""

    async def cleanup(self):
        await self.http.aclose()
        self._token = None

    async def complete_stream(self, messages, model, tools=None):
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        model_name = model.replace("copilot/", "")
        body = {"model": model_name, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token_str in _stream_sse(self.http, "https://api.githubcopilot.com/chat/completions", body, headers):
            yield token_str

    async def complete(self, messages, model, tools=None):
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        model_name = model.replace("copilot/", "")
        body = {"model": model_name, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post("https://api.githubcopilot.com/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class VertexAIProvider(LLMProvider):
    """Google Vertex AI Gemini API via httpx (requires ADC or service account JSON).

    Requires env: GOOGLE_APPLICATION_CREDENTIALS or VERTEX_AI_CREDENTIALS.
    """
    def __init__(self, **overrides):
        self.project = overrides.get("project") or os.environ.get("VERTEX_AI_PROJECT", "")
        self.location = overrides.get("location") or os.environ.get("VERTEX_AI_LOCATION", "us-central1")
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))
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
            else:
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

    async def complete_stream(self, messages, model, tools=None):
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
                        candidates = chunk.get("candidates", [])
                        for c in candidates:
                            content = c.get("content", {}).get("parts", [{}])[0].get("text", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue

    async def complete(self, messages, model, tools=None):
        token = await self._get_token()
        model_id = self._model_id(model)
        url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}/locations/{self.location}/publishers/google/models/{model_id}:generateContent"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        gemini_messages = _convert_to_gemini(messages)
        body = {"contents": gemini_messages}
        resp = await self.http.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        text = ""
        for c in candidates:
            parts = c.get("content", {}).get("parts", [])
            for p in parts:
                text += p.get("text", "")
        return LLMResponse(content=text, finish_reason="stop")


class BedrockProvider(LLMProvider):
    """Amazon Bedrock via AWS Signature V4 and httpx.

    Requires env: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION.
    """
    def __init__(self, **overrides):
        self.region = overrides.get("region") or os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        raw_key = overrides.get("api_key") or os.environ.get("AWS_ACCESS_KEY_ID", "")
        self.access_key = SecretStr(raw_key) if isinstance(raw_key, str) else raw_key
        self.secret_key = overrides.get("secret_key") or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self.session_token = overrides.get("session_token") or os.environ.get("AWS_SESSION_TOKEN", "")
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()
        self.access_key = SecretStr("")

    def _model_id(self, model: str) -> str:
        return model.replace("bedrock/", "")

    async def _signed_headers(self, method: str, url: str, body: bytes) -> dict[str, str]:
        service = "bedrock"
        amz_date = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        datestamp = amz_date[:8]

        parsed_url = urlparse(url)
        canonical_uri = parsed_url.path or "/"
        canonical_qs = parsed_url.query or ""

        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_headers = (
            f"content-type:application/json\n"
            f"host:{parsed_url.hostname}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "content-type;host;x-amz-date"
        canonical_request = (
            f"{method}\n"
            f"{canonical_uri}\n"
            f"{canonical_qs}\n"
            f"{canonical_headers}\n"
            f"{signed_headers}\n"
            f"{payload_hash}"
        )

        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{self.region}/{service}/aws4_request"
        string_to_sign = (
            f"{algorithm}\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
        )

        k_secret = f"AWS4{self.secret_key}".encode()
        k_date = hmac_mod.new(k_secret, datestamp.encode(), hashlib.sha256).digest()
        k_region = hmac_mod.new(k_date, self.region.encode(), hashlib.sha256).digest()
        k_service = hmac_mod.new(k_region, service.encode(), hashlib.sha256).digest()
        k_signing = hmac_mod.new(k_service, b"aws4_request", hashlib.sha256).digest()
        signature = hmac_mod.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

        authorization = (
            f"{algorithm} Credential={self.access_key.get_secret_value()}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Content-Type": "application/json",
            "X-Amz-Date": amz_date,
            "Authorization": authorization,
        }
        if self.session_token:
            headers["X-Amz-Security-Token"] = self.session_token
        return headers

    async def complete_stream(self, messages, model, tools=None):
        model_id = self._model_id(model)
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{model_id}/converse-stream"
        body = _convert_to_bedrock_converse(messages)
        headers = await self._signed_headers("POST", url, json.dumps(body).encode())
        async with self.http.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip() and line.startswith("data:"):
                    try:
                        chunk = json.loads(line[5:].strip())
                        if "contentBlockDelta" in chunk:
                            delta = chunk["contentBlockDelta"]["delta"]
                            if "text" in delta:
                                yield delta["text"]
                    except json.JSONDecodeError:
                        continue

    async def complete(self, messages, model, tools=None):
        model_id = self._model_id(model)
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{model_id}/converse"
        body = _convert_to_bedrock_converse(messages)
        headers = await self._signed_headers("POST", url, json.dumps(body).encode())
        resp = await self.http.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {}).get("message", {})
        content = " ".join(
            c.get("text", "") for c in output.get("content", []) if "text" in c
        )
        return LLMResponse(content=content, finish_reason=data.get("stopReason", "stop"))


def _convert_to_gemini(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents = []
    system = ""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system += content + "\n"
            continue
        parts = [{"text": content}]
        gemini_role = "user" if role in ("user", "tool") else "model"
        contents.append({"role": gemini_role, "parts": parts})
    result = contents
    return result


def _convert_to_bedrock_converse(messages: list[dict[str, Any]]) -> dict[str, Any]:
    converted = []
    system_text = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_text += content + "\n"
            continue
        bedrock_role = "assistant" if role == "assistant" else "user"
        converted.append({"role": bedrock_role, "content": [{"text": content}]})
    body: dict[str, Any] = {"messages": converted}
    if system_text:
        body["system"] = [{"text": system_text.strip()}]
    return body


class LLMRouter:
    _CACHE_TTL = 2.0
    _CACHE_MAXSIZE = 1024

    def __init__(self, providers_config: dict[str, Any] | None = None, llm_cache: LLMCache | None = None):
        self._providers: dict[str, LLMProvider] = {}
        self._providers_config = providers_config or {}
        self._cache: OrderedDict[str, tuple[float, LLMResponse]] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._rate_semaphore = asyncio.Semaphore(10)
        self._llm_cache = llm_cache

    async def cleanup(self):
        for p in self._providers.values():
            try:
                await p.cleanup()
            except (ConnectionError, TimeoutError):
                logger.warning("LLM provider cleanup failed: connection error")
        self._providers.clear()
        async with self._cache_lock:
            self._cache.clear()

    @staticmethod
    def _cache_key(messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None) -> str:
        return f"{model}|{tools}|{json.dumps(messages, sort_keys=True)}"

    async def _get_cached(self, key: str) -> LLMResponse | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry and (time.monotonic() - entry[0]) < LLMRouter._CACHE_TTL:
                self._cache.move_to_end(key)
                return entry[1]
            if entry:
                del self._cache[key]
            return None

    async def _set_cached(self, key: str, resp: LLMResponse):
        async with self._cache_lock:
            if len(self._cache) >= LLMRouter._CACHE_MAXSIZE:
                self._cache.popitem(last=False)
            self._cache[key] = (time.monotonic(), resp)

    def _get_provider(self, model: str) -> LLMProvider:
        if not model:
            model = settings.default_model
        if settings.ghost_mode:
            key = "ollama"
        elif model.startswith("openrouter/"):
            key = "openrouter"
        elif model.startswith("claude") or model.startswith("anthropic/"):
            key = "anthropic"
        elif model.startswith("ollama/"):
            key = "ollama"
        elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
            key = "openai"
        elif model.startswith("vllm/"):
            key = "vllm"
        elif model.startswith("copilot/"):
            key = "copilot"
        elif model.startswith("vertex/") or model.startswith("gemini/"):
            key = "vertex"
        elif model.startswith("bedrock/"):
            key = "bedrock"
        else:
            key = "ollama"
        if key not in self._providers:
            from raven.core.llm.factory import LLMProviderFactory
            overrides = dict(self._providers_config.get(key, {}))
            api_key = overrides.pop("api_key", None)
            raw = LLMProviderFactory.create(key, api_key=api_key, **overrides)
            self._providers[key] = InstrumentedLLMProvider(raw, provider_name=key)
        return self._providers[key]

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str | None = None, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        model = model or settings.default_model
        last_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                async with self._rate_semaphore:
                    provider = self._get_provider(model)
                    metrics.inc("llm_stream_start", {"model": model, "provider": type(provider).__name__})
                    with trace_llm_call(model=model):
                        async for token in provider.complete_stream(messages, model, tools):
                            yield token
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                last_exc = e
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM stream failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1, settings.llm_retry_max, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM stream failed after {} attempts: {}", settings.llm_retry_max, e)
                    metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM stream failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1, settings.llm_retry_max, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM stream failed after {} attempts: {}", settings.llm_retry_max, e)
                    metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
        raise last_exc or RuntimeError("LLM stream failed")

    async def complete(
        self, messages: list[dict[str, Any]], model: str | None = None, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        model = model or settings.default_model
        key = self._cache_key(messages, model, tools)
        cached = await self._get_cached(key)
        if cached is not None:
            metrics.inc("llm_cache_hit", {"model": model})
            return cached
        if self._llm_cache:
            redis_cached = await self._llm_cache.get(model, messages, tools)
            if redis_cached is not None:
                await self._set_cached(key, redis_cached)
                metrics.inc("llm_cache_hit", {"model": model})
                return redis_cached
        last_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                async with self._rate_semaphore:
                    provider = self._get_provider(model)
                    with trace_llm_call(model=model):
                        resp = await provider.complete(messages, model, tools)
                metrics.inc("llm_complete", {"model": model, "status": "ok"})
                if self._llm_cache:
                    await self._llm_cache.set(model, messages, resp, tools)
                await self._set_cached(key, resp)
                return resp
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                last_exc = e
                metrics.inc("llm_complete", {"model": model, "status": "retry"})
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM call failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1,
                        settings.llm_retry_max,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM call failed after {} attempts: {}", settings.llm_retry_max, e)
                    try:
                        logger.info("Failover: trying alternative models")
                        failover = ModelFailover(self)
                        return await failover.complete(messages, tools=tools)
                    except Exception as f:
                        last_exc = f
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                metrics.inc("llm_complete", {"model": model, "status": "retry"})
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM call failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1,
                        settings.llm_retry_max,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM call failed after {} attempts: {}", settings.llm_retry_max, e)
                    try:
                        logger.info("Failover: trying alternative models")
                        failover = ModelFailover(self)
                        return await failover.complete(messages, tools=tools)
                    except Exception as f:
                        last_exc = f
        metrics.inc("llm_complete", {"model": model, "status": "error"})
        raise last_exc or RuntimeError("LLM call failed")


async def default_provider_call(messages: list[dict[str, Any]]) -> dict[str, str]:
    router = LLMRouter()
    resp = await router.complete(messages)
    return {"content": resp.content}


def get_default_provider() -> Callable[..., Any]:
    return default_provider_call

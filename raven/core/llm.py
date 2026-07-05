from __future__ import annotations

import asyncio
import os
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from loguru import logger

from raven.core._json import json
from raven.core.config import settings
from raven.core.metrics import metrics
from raven.core.tracing import trace_llm_call


class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def __init__(self, id: str, name: str, arguments: dict[str, Any]):
        self.id = id
        self.name = name
        self.arguments = arguments

    def __repr__(self):
        return f"ToolCall(id={self.id}, name={self.name})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }

    @classmethod
    def from_openai(cls, tc: dict[str, Any]) -> ToolCall:
        args = (
            json.loads(tc["function"]["arguments"])
            if isinstance(tc["function"]["arguments"], str)
            else tc["function"]["arguments"]
        )
        return cls(id=tc["id"], name=tc["function"]["name"], arguments=args)


class LLMResponse:
    def __init__(self, content: str = "", tool_calls: list[ToolCall] | None = None, finish_reason: str = "stop"):
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason


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
    choice = data["choices"][0]
    msg = choice["message"]
    content = msg.get("content", "") or ""
    tool_calls_raw = msg.get("tool_calls")
    tool_calls = [ToolCall.from_openai(tc) for tc in tool_calls_raw] if tool_calls_raw else []
    return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=choice.get("finish_reason", "stop"))


class LLMProvider(ABC):
    @abstractmethod
    def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]: ...
    @abstractmethod
    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse: ...
    @abstractmethod
    async def cleanup(self):
        pass


class OpenRouterProvider(LLMProvider):
    def __init__(self, **overrides):
        self.api_key = overrides.get("api_key") or settings.openrouter_api_key
        self.base_url = overrides.get("base_url") or "https://openrouter.ai/api/v1"
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()

    async def _headers(self) -> dict[str, Any]:
        return {
            "Authorization": f"Bearer {self.api_key}",
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
        self.api_key = overrides.get("api_key") or settings.openai_api_key
        self.base_url = overrides.get("base_url") or "https://api.openai.com/v1"
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()

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
                "Authorization": f"Bearer {self.api_key}",
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
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class AnthropicProvider(LLMProvider):
    def __init__(self, **overrides):
        self.api_key = overrides.get("api_key") or settings.anthropic_api_key
        self.base_url = overrides.get("base_url") or "https://api.anthropic.com"
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()

    def _build_body(
        self, messages: list[dict[str, Any]], model: str, stream: bool, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        body = {
            "model": model,
            "messages": [m for m in messages if m["role"] != "system"],
            "system": next((m["content"] for m in messages if m["role"] == "system"), ""),
            "max_tokens": 4096,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
        return body

    def _headers(self) -> dict[str, Any]:
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}

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
        self.api_key = overrides.get("api_key") or ""
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        body = {"model": model.replace("vllm/", ""), "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async for token in _stream_sse(self.http, f"{self.base_url}/v1/chat/completions", body, headers):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        body = {"model": model.replace("vllm/", ""), "messages": messages}
        if tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = await self.http.post(f"{self.base_url}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class AzureProvider(LLMProvider):
    """Azure OpenAI — OpenAI-compatible API via Azure."""
    def __init__(self, **overrides):
        self.api_key = overrides.get("api_key") or os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.endpoint = overrides.get("base_url") or os.environ.get("AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com")
        self.api_version = overrides.get("api_version") or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()

    def _deployment(self, model: str) -> str:
        return model.replace("azure/", "")

    def _url(self, deployment: str) -> str:
        return f"{self.endpoint}/openai/deployments/{deployment}/chat/completions?api-version={self.api_version}"

    async def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "api-key": self.api_key}

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
        self._token: str | None = overrides.get("api_key") or os.environ.get("COPILOT_TOKEN") or None
        self._github_token = os.environ.get("GITHUB_TOKEN", "")

    async def _get_token(self) -> str:
        if self._token:
            return self._token
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
            self._token = data.get("token", self._github_token)
        except Exception as e:
            logger.warning("Failed to get Copilot token: {}", e)
            self._token = self._github_token
        return self._token or ""

    async def cleanup(self):
        await self.http.aclose()

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
        self._api_key = overrides.get("api_key") or ""
        self._token: str | None = None

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        import subprocess
        try:
            result = subprocess.run(
                ["gcloud", "auth", "print-access-token"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                self._token = result.stdout.strip()
                return self._token
        except FileNotFoundError:
            logger.debug("gcloud not found, trying credentials file")
        creds_path = os.environ.get("VERTEX_AI_CREDENTIALS") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if creds_path:
            import json as _json
            with open(creds_path) as f:
                creds = _json.load(f)
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
        self.access_key = overrides.get("api_key") or os.environ.get("AWS_ACCESS_KEY_ID", "")
        self.secret_key = overrides.get("secret_key") or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self.session_token = overrides.get("session_token") or os.environ.get("AWS_SESSION_TOKEN", "")
        self.http = httpx.AsyncClient(timeout=overrides.get("timeout", 120), limits=httpx.Limits(max_keepalive_connections=5, max_connections=20))

    async def cleanup(self):
        await self.http.aclose()

    def _model_id(self, model: str) -> str:
        return model.replace("bedrock/", "")

    async def _signed_headers(self, method: str, url: str, body: bytes) -> dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "application/json"}

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
    _cache: dict[str, tuple[float, LLMResponse]] = {}
    _CACHE_TTL = 2.0

    def __init__(self, providers_config: dict[str, Any] | None = None):
        self._providers: dict[str, LLMProvider] = {}
        self._providers_config = providers_config or {}

    async def cleanup(self):
        for p in self._providers.values():
            try:
                await p.cleanup()
            except (ConnectionError, TimeoutError):
                logger.warning("LLM provider cleanup failed: connection error")
        self._providers.clear()
        LLMRouter._cache.clear()

    @staticmethod
    def _cache_key(messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None) -> str:
        return f"{model}|{tools}|{json.dumps(messages, sort_keys=True)}"

    def _get_cached(self, key: str) -> LLMResponse | None:
        entry = LLMRouter._cache.get(key)
        if entry and (time.monotonic() - entry[0]) < LLMRouter._CACHE_TTL:
            return entry[1]
        if entry:
            del LLMRouter._cache[key]
        return None

    def _set_cached(self, key: str, resp: LLMResponse):
        LLMRouter._cache[key] = (time.monotonic(), resp)

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
            key = "azure"
        elif model.startswith("copilot/"):
            key = "copilot"
        elif model.startswith("vertex/") or model.startswith("gemini/"):
            key = "vertex"
        elif model.startswith("bedrock/"):
            key = "bedrock"
        else:
            key = "ollama"
        if key not in self._providers:
            mapping = {
                "openrouter": OpenRouterProvider,
                "anthropic": AnthropicProvider,
                "ollama": OllamaProvider,
                "openai": OpenAIProvider,
                "vllm": VLLMProvider,
                "azure": AzureProvider,
                "copilot": CopilotProvider,
                "vertex": VertexAIProvider,
                "bedrock": BedrockProvider,
            }
            overrides = self._providers_config.get(key, {})
            self._providers[key] = mapping[key](**overrides)  # type: ignore[abstract]
        return self._providers[key]

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str | None = None, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        model = model or settings.default_model
        last_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                provider = self._get_provider(model)
                metrics.inc("llm_stream_start", {"model": model, "provider": type(provider).__name__})
                with trace_llm_call(model=model):
                    async for token in provider.complete_stream(messages, model, tools):
                        yield token
                return
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
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
        cached = self._get_cached(key)
        if cached is not None:
            metrics.inc("llm_cache_hit", {"model": model})
            return cached
        last_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                provider = self._get_provider(model)
                with trace_llm_call(model=model):
                    resp = await provider.complete(messages, model, tools)
                metrics.inc("llm_complete", {"model": model, "status": "ok"})
                self._set_cached(key, resp)
                return resp
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
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
                    from raven.core.failover import ModelFailover
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

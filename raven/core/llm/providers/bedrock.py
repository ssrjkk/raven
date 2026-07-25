from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import SecretStr

from raven.core._json import json
from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.llm.providers.base import _convert_to_bedrock_converse


class BedrockProvider(LLMProvider):
    def __init__(self, **overrides):
        self.region = overrides.get("region") or os.environ.get(
            "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        )
        raw_key = overrides.get("api_key") or os.environ.get("AWS_ACCESS_KEY_ID", "")
        self.access_key = SecretStr(raw_key) if isinstance(raw_key, str) else raw_key
        self.secret_key = overrides.get("secret_key") or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self.session_token = overrides.get("session_token") or os.environ.get("AWS_SESSION_TOKEN", "")
        import httpx

        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

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
        canonical_headers = f"content-type:application/json\nhost:{parsed_url.hostname}\nx-amz-date:{amz_date}\n"
        signed_headers = "content-type;host;x-amz-date"
        canonical_request = (
            f"{method}\n{canonical_uri}\n{canonical_qs}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        )
        algorithm = "AWS4-HMAC-SHA256"
        credential_scope = f"{datestamp}/{self.region}/{service}/aws4_request"
        string_to_sign = (
            f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
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

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
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

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        model_id = self._model_id(model)
        url = f"https://bedrock-runtime.{self.region}.amazonaws.com/model/{model_id}/converse"
        body = _convert_to_bedrock_converse(messages)
        headers = await self._signed_headers("POST", url, json.dumps(body).encode())
        resp = await self.http.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {}).get("message", {})
        content = " ".join(c.get("text", "") for c in output.get("content", []) if "text" in c)
        return LLMResponse(content=content, finish_reason=data.get("stopReason", "stop"))

from __future__ import annotations

import hashlib
import json
from typing import Any

from loguru import logger

from raven.core.cache.redis_client import RedisClient
from raven.core.llm.protocol import LLMResponse

_DEFAULT_TTL = 300
_DEFAULT_SCAN_BATCH = 100
_MAX_INVALIDATE_KEYS = 10_000


class LLMCache:
    def __init__(
        self, redis_client: RedisClient, ttl: int = _DEFAULT_TTL, scan_batch: int = _DEFAULT_SCAN_BATCH
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl
        self._scan_batch = scan_batch

    @staticmethod
    def _build_key(model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> str:
        payload = json.dumps(
            {"messages": messages, "tools": tools},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return f"llm_cache:{model}:{digest}"

    @staticmethod
    def _serialize_response(response: LLMResponse) -> str:
        tool_calls_data = []
        for tc in response.tool_calls:
            if hasattr(tc, "to_dict"):
                tool_calls_data.append(tc.to_dict())
            else:
                tool_calls_data.append({"id": getattr(tc, "id", ""), "name": getattr(tc, "name", ""), "arguments": getattr(tc, "arguments", {})})
        return json.dumps(
            {
                "content": response.content,
                "tool_calls": tool_calls_data,
                "finish_reason": response.finish_reason,
            }
        )

    async def get(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse | None:
        if not self._redis.is_healthy:
            return None
        client = self._redis._client
        if client is None:
            return None
        key = self._build_key(model, messages, tools)
        try:
            raw = await self._redis._execute_with_retry("get", client.get, key)
            if raw is None:
                return None
            data = json.loads(raw)
            from raven.core.llm.protocol import ToolCall

            raw_tool_calls = data.get("tool_calls", [])
            tool_calls = [
                ToolCall(id=tc.get("id", ""), name=tc.get("name", ""), arguments=tc.get("arguments", {}))
                if isinstance(tc, dict) else tc
                for tc in raw_tool_calls
            ]
            return LLMResponse(
                content=data.get("content", ""),
                tool_calls=tool_calls,
                finish_reason=data.get("finish_reason", "stop"),
            )
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.debug("llm_cache.decode_error", key=key, error=str(e))
            return None
        except Exception as e:
            logger.warning("llm_cache.get_error", key=key, error=str(e))
            return None

    async def set(
        self,
        model: str,
        messages: list[dict[str, Any]],
        response: LLMResponse,
        tools: list[dict[str, Any]] | None = None,
    ) -> bool:
        if not self._redis.is_healthy:
            return False
        client = self._redis._client
        if client is None:
            return False
        key = self._build_key(model, messages, tools)
        try:
            data = self._serialize_response(response)
            await self._redis._execute_with_retry("set", client.set, key, data, ex=self._ttl)
            return True
        except Exception as e:
            logger.warning("llm_cache.set_error", key=key, model=model, error=str(e))
            return False

    async def invalidate(self, model: str, max_keys: int = _MAX_INVALIDATE_KEYS) -> int:
        if not self._redis.is_healthy:
            return 0
        client = self._redis._client
        if client is None:
            return 0
        pattern = f"llm_cache:{model}:*"
        try:
            cursor = 0
            deleted = 0
            total_scanned = 0
            while True:
                cursor, keys = await self._redis._execute_with_retry(
                    "scan",
                    client.scan,
                    cursor=cursor,
                    match=pattern,
                    count=self._scan_batch,
                )
                total_scanned += len(keys)
                if keys:
                    count = await self._redis._execute_with_retry("delete", client.delete, *keys)
                    deleted += count
                if cursor == 0 or total_scanned >= max_keys:
                    if total_scanned >= max_keys:
                        logger.warning("llm_cache.invalidate_truncated", model=model, max_keys=max_keys)
                    break
            return deleted
        except Exception as e:
            logger.warning("llm_cache.invalidate_error", model=model, pattern=pattern, error=str(e))
            return 0

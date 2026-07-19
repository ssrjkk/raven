from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from raven.core.cache.redis_client import RedisClient
from raven.core.models import Session

_DEFAULT_TTL = 86400


class SessionStore:
    def __init__(self, redis_client: RedisClient, ttl: int = _DEFAULT_TTL) -> None:
        self._redis = redis_client
        self._ttl = ttl

    @staticmethod
    def _key(session_id: str) -> str:
        return f"session:{session_id}"

    async def get(self, session_id: str) -> Session | None:
        if not self._redis.is_healthy:
            return None
        client = self._redis._client
        if client is None:
            return None
        try:
            data = await self._redis._execute_with_retry("hgetall", client.hgetall, self._key(session_id))
            if not data:
                return None
            await self._redis._execute_with_retry("expire", client.expire, self._key(session_id), self._ttl)
            return Session(
                id=data.get("id", session_id),
                channel=data.get("channel", ""),
                user_id=data.get("user_id", ""),
                agent_id=data.get("agent_id", "default"),
                agent_skills=SessionStore._parse_json_list(data.get("agent_skills", "[]")),
                system_prompt=data.get("system_prompt"),
                created_at=SessionStore._parse_iso(data.get("created_at", "")),
                updated_at=SessionStore._parse_iso(data.get("updated_at", "")),
            )
        except Exception as e:
            logger.warning("session_store.get_error", session_id=session_id, error=str(e))
            return None

    async def set(self, session: Session) -> bool:
        if not self._redis.is_healthy:
            return False
        client = self._redis._client
        if client is None:
            return False
        key = self._key(session.id)
        try:
            mapping: dict[str, str] = {
                "id": session.id,
                "channel": session.channel,
                "user_id": session.user_id,
                "agent_id": session.agent_id,
                "agent_skills": SessionStore._to_json_list(session.agent_skills),
                "created_at": session.created_at.isoformat() if session.created_at else datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            if session.system_prompt is not None:
                mapping["system_prompt"] = session.system_prompt
            await self._redis._execute_with_retry("hset", client.hset, key, mapping=mapping)
            await self._redis._execute_with_retry("expire", client.expire, key, self._ttl)
            return True
        except Exception as e:
            logger.warning("session_store.set_error", session_id=session.id, error=str(e))
            return False

    async def update(self, session_id: str, **fields: Any) -> bool:
        if not self._redis.is_healthy:
            return False
        client = self._redis._client
        if client is None:
            return False
        key = self._key(session_id)
        try:
            mapping: dict[str, str] = {}
            for k, v in fields.items():
                if k in ("agent_skills",):
                    mapping[k] = SessionStore._to_json_list(v)
                elif k in ("created_at", "updated_at", "timestamp"):
                    mapping[k] = v.isoformat() if isinstance(v, datetime) else str(v)
                else:
                    mapping[k] = v if v is not None else ""
            mapping["updated_at"] = datetime.now(UTC).isoformat()
            await self._redis._execute_with_retry("hset", client.hset, key, mapping=mapping)
            await self._redis._execute_with_retry("expire", client.expire, key, self._ttl)
            return True
        except Exception as e:
            logger.warning("session_store.update_error", session_id=session_id, error=str(e))
            return False

    async def delete(self, session_id: str) -> bool:
        if not self._redis.is_healthy:
            return False
        client = self._redis._client
        if client is None:
            return False
        try:
            deleted = await self._redis._execute_with_retry("delete", client.delete, self._key(session_id))
            return bool(deleted)
        except Exception as e:
            logger.warning("session_store.delete_error", session_id=session_id, error=str(e))
            return False

    async def exists(self, session_id: str) -> bool:
        if not self._redis.is_healthy:
            return False
        client = self._redis._client
        if client is None:
            return False
        try:
            result = await self._redis._execute_with_retry("exists", client.exists, self._key(session_id))
            return bool(result)
        except Exception as e:
            logger.warning("session_store.exists_error", session_id=session_id, error=str(e))
            return False

    @staticmethod
    def _parse_iso(value: str) -> datetime:
        if not value:
            return datetime.now(UTC)
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return datetime.now(UTC)

    @staticmethod
    def _parse_json_list(value: str) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return list(parsed) if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _to_json_list(value: Any) -> str:
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except json.JSONDecodeError:
                return json.dumps([value])
        if isinstance(value, list):
            return json.dumps(value)
        return json.dumps([])

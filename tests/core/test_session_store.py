from __future__ import annotations

import json
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from raven.core.cache.redis_client import RedisClient
from raven.core.cache.session_store import SessionStore
from raven.core.models import Session

_SESSION_ID = "sess-1"
_TTL = 3600
_KEY = f"session:{_SESSION_ID}"


class _FakeRedis:
    """In-memory double for RedisClient backed by an AsyncMock client."""

    def __init__(self) -> None:
        self._client: Any = AsyncMock()
        self._is_healthy = True

    @property
    def is_healthy(self) -> bool:
        return self._is_healthy

    async def _execute_with_retry(self, operation: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    def set_healthy(self, healthy: bool) -> None:
        self._is_healthy = healthy

    def set_client(self, client: Any) -> None:
        self._client = client


@pytest.fixture
def store_and_redis() -> Generator[tuple[SessionStore, _FakeRedis], None, None]:
    redis = _FakeRedis()
    store = SessionStore(cast("RedisClient", redis), ttl=_TTL)
    yield store, redis


def _hset_mapping(redis: _FakeRedis) -> dict[str, str]:
    call = redis._client.hset.await_args
    assert call is not None
    args, kwargs = call
    assert args[0] == _KEY
    mapping = kwargs["mapping"]
    assert isinstance(mapping, dict)
    return mapping


class TestKey:
    def test_key_prefixes_session_id(self) -> None:
        assert SessionStore._key(_SESSION_ID) == _KEY


class TestInit:
    async def test_uses_default_ttl_when_not_provided(self) -> None:
        redis = _FakeRedis()
        store = SessionStore(cast("RedisClient", redis))
        ok = await store.set(Session(id=_SESSION_ID, channel="webchat", user_id="user-1"))
        assert ok is True
        redis._client.expire.assert_awaited_once_with(_KEY, 86400)


class TestGet:
    async def test_returns_none_when_redis_unhealthy(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_healthy(False)
        assert await store.get(_SESSION_ID) is None
        redis._client.hgetall.assert_not_awaited()

    async def test_returns_none_when_client_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_client(None)
        assert await store.get(_SESSION_ID) is None

    async def test_returns_none_when_no_data(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.hgetall.return_value = {}
        assert await store.get(_SESSION_ID) is None
        redis._client.expire.assert_not_awaited()

    async def test_returns_parsed_session(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        created = datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC)
        updated = datetime(2024, 5, 2, 13, 30, 0, tzinfo=UTC)
        redis._client.hgetall.return_value = {
            "id": _SESSION_ID,
            "channel": "webchat",
            "user_id": "user-1",
            "agent_id": "agent-x",
            "agent_skills": '["python", "pytest"]',
            "system_prompt": "be concise",
            "created_at": created.isoformat(),
            "updated_at": updated.isoformat(),
        }
        result = await store.get(_SESSION_ID)
        assert result is not None
        assert result.id == _SESSION_ID
        assert result.channel == "webchat"
        assert result.user_id == "user-1"
        assert result.agent_id == "agent-x"
        assert result.agent_skills == ["python", "pytest"]
        assert result.system_prompt == "be concise"
        assert result.created_at == created
        assert result.updated_at == updated
        redis._client.expire.assert_awaited_once_with(_KEY, _TTL)

    async def test_applies_defaults_when_fields_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.hgetall.return_value = {"id": "other-id"}
        result = await store.get(_SESSION_ID)
        assert result is not None
        assert result.id == "other-id"
        assert result.channel == ""
        assert result.user_id == ""
        assert result.agent_id == "default"
        assert result.agent_skills == []
        assert result.system_prompt is None

    async def test_handles_bad_json_and_dates(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.hgetall.return_value = {
            "agent_skills": "not-json",
            "created_at": "garbage",
            "updated_at": "",
        }
        result = await store.get(_SESSION_ID)
        assert result is not None
        assert result.agent_skills == []
        assert isinstance(result.created_at, datetime)
        assert isinstance(result.updated_at, datetime)

    async def test_returns_none_on_redis_error(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.hgetall.side_effect = RuntimeError("boom")
        assert await store.get(_SESSION_ID) is None


class TestSet:
    async def test_returns_false_when_redis_unhealthy(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_healthy(False)
        session = Session(id=_SESSION_ID, channel="webchat", user_id="user-1")
        assert await store.set(session) is False
        redis._client.hset.assert_not_awaited()

    async def test_returns_false_when_client_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_client(None)
        session = Session(id=_SESSION_ID, channel="webchat", user_id="user-1")
        assert await store.set(session) is False

    async def test_stores_all_fields(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        created = datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC)
        session = Session(
            id=_SESSION_ID,
            channel="webchat",
            user_id="user-1",
            agent_id="agent-x",
            agent_skills=["python", "pytest"],
            system_prompt="be concise",
            created_at=created,
        )
        ok = await store.set(session)
        assert ok is True
        mapping = _hset_mapping(redis)
        assert mapping["id"] == _SESSION_ID
        assert mapping["channel"] == "webchat"
        assert mapping["user_id"] == "user-1"
        assert mapping["agent_id"] == "agent-x"
        assert json.loads(mapping["agent_skills"]) == ["python", "pytest"]
        assert mapping["system_prompt"] == "be concise"
        assert mapping["created_at"] == created.isoformat()
        assert "updated_at" in mapping
        redis._client.expire.assert_awaited_once_with(_KEY, _TTL)

    async def test_omits_system_prompt_when_none(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        session = Session(id=_SESSION_ID, channel="webchat", user_id="user-1")
        ok = await store.set(session)
        assert ok is True
        assert "system_prompt" not in _hset_mapping(redis)

    async def test_uses_now_when_created_at_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        session = Session(id=_SESSION_ID, channel="webchat", user_id="user-1")
        session.created_at = cast("datetime", None)
        before = datetime.now(UTC)
        ok = await store.set(session)
        after = datetime.now(UTC)
        assert ok is True
        created_at = datetime.fromisoformat(_hset_mapping(redis)["created_at"])
        assert before <= created_at <= after

    async def test_returns_false_on_redis_error(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.hset.side_effect = RuntimeError("boom")
        session = Session(id=_SESSION_ID, channel="webchat", user_id="user-1")
        assert await store.set(session) is False


class TestUpdate:
    async def test_returns_false_when_redis_unhealthy(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_healthy(False)
        assert await store.update(_SESSION_ID, channel="telegram") is False

    async def test_returns_false_when_client_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_client(None)
        assert await store.update(_SESSION_ID, channel="telegram") is False

    async def test_sets_known_fields(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        ok = await store.update(_SESSION_ID, channel="telegram", user_id="user-2", agent_id="agent-y")
        assert ok is True
        mapping = _hset_mapping(redis)
        assert mapping["channel"] == "telegram"
        assert mapping["user_id"] == "user-2"
        assert mapping["agent_id"] == "agent-y"
        assert "updated_at" in mapping
        redis._client.expire.assert_awaited_once_with(_KEY, _TTL)

    async def test_serializes_agent_skills(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        ok = await store.update(_SESSION_ID, agent_skills=["a", "b"])
        assert ok is True
        assert json.loads(_hset_mapping(redis)["agent_skills"]) == ["a", "b"]

    async def test_serializes_datetime_field(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        when = datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC)
        ok = await store.update(_SESSION_ID, channel=when)
        assert ok is True
        assert _hset_mapping(redis)["channel"] == when.isoformat()

    async def test_stringifies_scalar_field(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        ok = await store.update(_SESSION_ID, channel=42)
        assert ok is True
        assert _hset_mapping(redis)["channel"] == "42"

    async def test_none_value_becomes_empty_string(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        ok = await store.update(_SESSION_ID, user_id=None)
        assert ok is True
        assert _hset_mapping(redis)["user_id"] == ""

    async def test_unknown_field_only_returns_false(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        assert await store.update(_SESSION_ID, bogus="x") is False
        redis._client.hset.assert_not_awaited()
        redis._client.expire.assert_not_awaited()

    async def test_ignores_unknown_field_but_updates_known(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        ok = await store.update(_SESSION_ID, bogus="x", channel="discord")
        assert ok is True
        mapping = _hset_mapping(redis)
        assert mapping["channel"] == "discord"
        assert "bogus" not in mapping

    async def test_returns_false_on_redis_error(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.hset.side_effect = RuntimeError("boom")
        assert await store.update(_SESSION_ID, channel="telegram") is False


class TestTouch:
    async def test_returns_false_when_redis_unhealthy(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_healthy(False)
        assert await store.touch(_SESSION_ID) is False

    async def test_returns_false_when_client_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_client(None)
        assert await store.touch(_SESSION_ID) is False

    async def test_returns_false_when_key_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.exists.return_value = 0
        assert await store.touch(_SESSION_ID) is False
        redis._client.expire.assert_not_awaited()

    async def test_refreshes_ttl_when_key_exists(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.exists.return_value = 1
        assert await store.touch(_SESSION_ID) is True
        redis._client.exists.assert_awaited_once_with(_KEY)
        redis._client.expire.assert_awaited_once_with(_KEY, _TTL)

    async def test_returns_false_on_redis_error(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.exists.side_effect = RuntimeError("boom")
        assert await store.touch(_SESSION_ID) is False


class TestDelete:
    async def test_returns_false_when_redis_unhealthy(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_healthy(False)
        assert await store.delete(_SESSION_ID) is False

    async def test_returns_false_when_client_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_client(None)
        assert await store.delete(_SESSION_ID) is False

    async def test_returns_true_when_deleted(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.delete.return_value = 1
        assert await store.delete(_SESSION_ID) is True
        redis._client.delete.assert_awaited_once_with(_KEY)

    async def test_returns_false_when_key_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.delete.return_value = 0
        assert await store.delete(_SESSION_ID) is False

    async def test_returns_false_on_redis_error(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.delete.side_effect = RuntimeError("boom")
        assert await store.delete(_SESSION_ID) is False


class TestExists:
    async def test_returns_false_when_redis_unhealthy(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_healthy(False)
        assert await store.exists(_SESSION_ID) is False

    async def test_returns_false_when_client_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis.set_client(None)
        assert await store.exists(_SESSION_ID) is False

    async def test_returns_true_when_key_present(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.exists.return_value = 1
        assert await store.exists(_SESSION_ID) is True
        redis._client.exists.assert_awaited_once_with(_KEY)

    async def test_returns_false_when_key_missing(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.exists.return_value = 0
        assert await store.exists(_SESSION_ID) is False

    async def test_returns_false_on_redis_error(self, store_and_redis: tuple[SessionStore, _FakeRedis]) -> None:
        store, redis = store_and_redis
        redis._client.exists.side_effect = RuntimeError("boom")
        assert await store.exists(_SESSION_ID) is False


class TestParseIso:
    def test_empty_returns_now(self) -> None:
        result = SessionStore._parse_iso("")
        assert result.tzinfo == UTC
        assert abs((datetime.now(UTC) - result).total_seconds()) < 5

    def test_valid_iso_parsed(self) -> None:
        expected = datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC)
        assert SessionStore._parse_iso("2024-05-01T12:00:00+00:00") == expected

    def test_invalid_string_falls_back_to_now(self) -> None:
        result = SessionStore._parse_iso("not-a-date")
        assert result.tzinfo == UTC
        assert abs((datetime.now(UTC) - result).total_seconds()) < 5

    def test_non_string_falls_back_to_now(self) -> None:
        result = SessionStore._parse_iso(cast("str", 123))
        assert result.tzinfo == UTC
        assert abs((datetime.now(UTC) - result).total_seconds()) < 5


class TestParseJsonList:
    def test_empty_returns_empty(self) -> None:
        assert SessionStore._parse_json_list("") == []

    def test_parses_json_list(self) -> None:
        assert SessionStore._parse_json_list('["a", "b"]') == ["a", "b"]

    def test_non_list_json_returns_empty(self) -> None:
        assert SessionStore._parse_json_list('{"a": 1}') == []

    def test_invalid_json_returns_empty(self) -> None:
        assert SessionStore._parse_json_list("not-json") == []

    def test_non_string_returns_empty(self) -> None:
        assert SessionStore._parse_json_list(cast("str", 123)) == []


class TestToJsonList:
    def test_valid_json_string_passthrough(self) -> None:
        assert SessionStore._to_json_list('["a", "b"]') == '["a", "b"]'

    def test_invalid_json_string_wrapped(self) -> None:
        assert SessionStore._to_json_list("plain") == '["plain"]'

    def test_list_serialized(self) -> None:
        assert SessionStore._to_json_list(["a", "b"]) == '["a", "b"]'

    def test_other_types_return_empty_list(self) -> None:
        assert SessionStore._to_json_list(None) == "[]"
        assert SessionStore._to_json_list({"a": 1}) == "[]"

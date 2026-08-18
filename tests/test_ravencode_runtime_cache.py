from __future__ import annotations

from collections.abc import Generator

import pytest

import ravencode.runtime.cache as cache_mod
from ravencode.runtime.cache import ResponseCache, get_cache


@pytest.fixture(autouse=True)
def reset_cache() -> Generator[None, None, None]:
    cache_mod._cache = None
    yield
    cache_mod._cache = None


class TestResponseCache:
    def test_miss_returns_none(self) -> None:
        assert ResponseCache().get([{"role": "user", "content": "hi"}]) is None

    def test_set_and_get(self) -> None:
        cache = ResponseCache()
        messages = [{"role": "user", "content": "hi"}]
        cache.set(messages, "answer")
        assert cache.get(messages) == "answer"

    def test_get_with_tools(self) -> None:
        cache = ResponseCache()
        tools = [{"name": "bash"}]
        cache.set([{"role": "user", "content": "x"}], "v", tools)
        assert cache.get([{"role": "user", "content": "x"}], tools) == "v"

    def test_key_ignores_order(self) -> None:
        cache = ResponseCache()
        a = [{"role": "user", "content": "hi"}]
        b = [{"content": "hi", "role": "user"}]
        cache.set(a, "v")
        assert cache.get(b) == "v"

    def test_tools_part_of_key(self) -> None:
        cache = ResponseCache()
        messages = [{"role": "user", "content": "x"}]
        cache.set(messages, "v", [{"name": "bash"}])
        assert cache.get(messages, [{"name": "edit"}]) is None

    def test_ttl_expiry(self, monkeypatch) -> None:
        cache = ResponseCache(ttl=10.0)
        now = [100.0]
        monkeypatch.setattr("ravencode.runtime.cache.time.time", lambda: now[0])
        messages = [{"role": "user", "content": "x"}]
        cache.set(messages, "v")
        now[0] = 115.0
        assert cache.get(messages) is None

    def test_ttl_not_expired(self, monkeypatch) -> None:
        cache = ResponseCache(ttl=10.0)
        now = [100.0]
        monkeypatch.setattr("ravencode.runtime.cache.time.time", lambda: now[0])
        messages = [{"role": "user", "content": "x"}]
        cache.set(messages, "v")
        now[0] = 109.0
        assert cache.get(messages) == "v"

    def test_get_refreshes_order(self, monkeypatch) -> None:
        cache = ResponseCache(max_size=2)
        now = [100.0]
        monkeypatch.setattr("ravencode.runtime.cache.time.time", lambda: now[0])
        cache.set([{"role": "user", "content": "a"}], "1")
        cache.set([{"role": "user", "content": "b"}], "2")
        assert cache.get([{"role": "user", "content": "a"}]) == "1"
        cache.set([{"role": "user", "content": "c"}], "3")
        assert cache.get([{"role": "user", "content": "a"}]) == "1"
        assert cache.get([{"role": "user", "content": "b"}]) is None

    def test_lru_eviction(self, monkeypatch) -> None:
        cache = ResponseCache(max_size=2)
        monkeypatch.setattr("ravencode.runtime.cache.time.time", lambda: 100.0)
        cache.set([{"role": "user", "content": "a"}], "1")
        cache.set([{"role": "user", "content": "b"}], "2")
        cache.set([{"role": "user", "content": "c"}], "3")
        assert cache.get([{"role": "user", "content": "a"}]) is None
        assert cache.get([{"role": "user", "content": "b"}]) == "2"
        assert cache.size == 2

    def test_clear(self) -> None:
        cache = ResponseCache()
        cache.set([{"role": "user", "content": "x"}], "v")
        cache.clear()
        assert cache.size == 0
        assert cache.get([{"role": "user", "content": "x"}]) is None

    def test_size_property(self) -> None:
        cache = ResponseCache()
        assert cache.size == 0
        cache.set([{"role": "user", "content": "a"}], "1")
        cache.set([{"role": "user", "content": "b"}], "2")
        assert cache.size == 2

    def test_expired_entry_removed(self, monkeypatch) -> None:
        cache = ResponseCache(ttl=5.0)
        now = [100.0]
        monkeypatch.setattr("ravencode.runtime.cache.time.time", lambda: now[0])
        cache.set([{"role": "user", "content": "x"}], "v")
        assert cache.size == 1
        now[0] = 200.0
        assert cache.get([{"role": "user", "content": "x"}]) is None
        assert cache.size == 0


class TestGetCache:
    def test_singleton(self) -> None:
        assert get_cache() is get_cache()

    def test_reinitialized_when_none(self) -> None:
        first = get_cache()
        cache_mod._cache = None
        second = get_cache()
        assert second is not first
        assert isinstance(second, ResponseCache)

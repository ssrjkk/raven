from __future__ import annotations

import time

from ravencode.runtime.cache import ResponseCache, get_cache


class TestResponseCache:
    def test_miss_returns_none(self):
        cache = ResponseCache()
        assert cache.get([{"role": "user", "content": "hi"}]) is None

    def test_set_and_get(self):
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "hello"}]
        cache.set(msgs, "world")
        assert cache.get(msgs) == "world"

    def test_different_messages_different_keys(self):
        cache = ResponseCache()
        cache.set([{"role": "user", "content": "hello"}], "world")
        assert cache.get([{"role": "user", "content": "bye"}]) is None

    def test_order_matters(self):
        cache = ResponseCache()
        cache.set([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}], "ab")
        assert cache.get([{"role": "user", "content": "b"}, {"role": "user", "content": "a"}]) is None

    def test_ttl_expiry(self):
        cache = ResponseCache(max_size=10, ttl=0.05)
        msgs = [{"role": "user", "content": "fast"}]
        cache.set(msgs, "value")
        assert cache.get(msgs) == "value"
        time.sleep(0.1)
        assert cache.get(msgs) is None

    def test_lru_eviction(self):
        cache = ResponseCache(max_size=2)
        cache.set([{"role": "user", "content": "a"}], "1")
        cache.set([{"role": "user", "content": "b"}], "2")
        cache.set([{"role": "user", "content": "c"}], "3")
        assert cache.get([{"role": "user", "content": "a"}]) is None
        assert cache.get([{"role": "user", "content": "c"}]) == "3"

    def test_access_refreshes_position(self):
        cache = ResponseCache(max_size=2)
        cache.set([{"role": "user", "content": "a"}], "1")
        cache.set([{"role": "user", "content": "b"}], "2")
        cache.get([{"role": "user", "content": "a"}])
        cache.set([{"role": "user", "content": "c"}], "3")
        assert cache.get([{"role": "user", "content": "a"}]) == "1"
        assert cache.get([{"role": "user", "content": "b"}]) is None

    def test_clear(self):
        cache = ResponseCache()
        cache.set([{"role": "user", "content": "x"}], "y")
        cache.clear()
        assert cache.size == 0

    def test_size_property(self):
        cache = ResponseCache()
        assert cache.size == 0
        cache.set([{"role": "user", "content": "a"}], "1")
        assert cache.size == 1
        cache.set([{"role": "user", "content": "b"}], "2")
        assert cache.size == 2

    def test_tools_param_affects_key(self):
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "hi"}]
        tools = [{"name": "read", "description": "read files"}]
        cache.set(msgs, "with-tools", tools=tools)
        assert cache.get(msgs) is None
        assert cache.get(msgs, tools=tools) == "with-tools"

    def test_none_value_returns_none(self):
        cache = ResponseCache()
        msgs = [{"role": "user", "content": "x"}]
        cache.set(msgs, "something")
        assert cache.get(msgs) == "something"

    def test_large_content(self):
        cache = ResponseCache(max_size=10)
        long_msg = [{"role": "user", "content": "x" * 10000}]
        cache.set(long_msg, "y" * 10000)
        assert cache.get(long_msg) == "y" * 10000


class TestGetCache:
    def test_singleton(self):
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2
        assert isinstance(c1, ResponseCache)
        c1.clear()

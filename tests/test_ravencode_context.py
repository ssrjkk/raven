from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from ravencode.runtime.context import Conversation, MemoryStore, create_conversation


class TestMemoryStore:
    def _temp_path(self):
        import os
        fd, path = tempfile.mkstemp(suffix=".json", text=True)
        os.write(fd, b"{}")
        os.close(fd)
        return path

    def test_set_and_get(self):
        path = self._temp_path()
        try:
            store = MemoryStore(path=path)

            async def run():
                await store.set("key1", "val1")
                v = await store.get("key1")
                assert v == "val1"

            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_get_default(self):
        store = MemoryStore(path=":memory:")
        assert asyncio.run(store.get("missing", "fallback")) == "fallback"

    def test_delete(self):
        path = self._temp_path()
        try:
            store = MemoryStore(path=path)

            async def run():
                await store.set("x", 1)
                await store.delete("x")
                v = await store.get("x")
                assert v is None

            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_clear(self):
        path = self._temp_path()
        try:
            store = MemoryStore(path=path)

            async def run():
                await store.set("a", 1)
                await store.set("b", 2)
                await store.clear()
                assert await store.keys() == []

            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_keys(self):
        path = self._temp_path()
        try:
            store = MemoryStore(path=path)

            async def run():
                await store.set("a", 1)
                await store.set("b", 2)
                ks = await store.keys()
                assert sorted(ks) == ["a", "b"]

            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_contains(self):
        path = self._temp_path()
        try:
            store = MemoryStore(path=path)

            async def run():
                await store.set("x", 42)
                assert "x" in store
                assert "y" not in store

            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_dict_interface(self):
        path = self._temp_path()
        try:
            store = MemoryStore(path=path)

            async def run():
                store["key"] = "value"
                await asyncio.sleep(0.05)
                assert store["key"] == "value"
                del store["key"]
                assert "key" not in store

            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_to_dict(self):
        path = self._temp_path()
        try:
            store = MemoryStore(path=path)

            async def run():
                await store.set("a", 1)
                await store.set("b", 2)
                assert store.to_dict() == {"a": 1, "b": 2}

            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_persists_to_disk(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            async def run():
                store = MemoryStore(path=path)
                await store.set("saved", "data")
                await asyncio.sleep(0.05)
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                assert data["saved"] == "data"
            asyncio.run(run())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_loads_from_disk(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            json.dump({"preload": "value"}, f)
            path = f.name
        try:
            store = MemoryStore(path=path)
            assert store["preload"] == "value"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_corrupt_json_falls_back_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            f.write("not valid json{")
            path = f.name
        try:
            store = MemoryStore(path=path)
            assert store.to_dict() == {}
        finally:
            Path(path).unlink(missing_ok=True)


class TestConversation:
    def test_initializes_with_system_prompt(self):
        c = Conversation(system_prompt="You are a test bot.")
        assert c.messages[0]["role"] == "system"
        assert c.messages[0]["content"] == "You are a test bot."

    def test_add_user_message(self):
        c = Conversation(system_prompt="test")
        c.add_user_message("hello")
        assert len(c.messages) == 2
        assert c.messages[1] == {"role": "user", "content": "hello"}

    def test_add_assistant_message(self):
        c = Conversation(system_prompt="test")
        c.add_assistant_message("hi there")
        assert c.messages[1]["role"] == "assistant"

    def test_add_tool_result(self):
        c = Conversation(system_prompt="test")
        c.add_tool_result("call_1", "result")
        assert c.messages[1]["role"] == "tool"
        assert c.messages[1]["tool_call_id"] == "call_1"

    def test_message_count(self):
        c = Conversation(system_prompt="test")
        assert c.message_count == 0
        c.add_user_message("hi")
        assert c.message_count == 1

    def test_get_messages(self):
        c = Conversation(system_prompt="test")
        c.add_user_message("q")
        msgs = c.get_messages()
        assert len(msgs) == 2
        assert msgs[1]["content"] == "q"

    def test_estimate_tokens(self):
        c = Conversation(system_prompt="test")
        assert c._estimate_tokens("hello world") == 2 + 2
        assert c._estimate_tokens("a" * 100) == 25 + 1

    def test_trim_removes_oldest_when_over_limit(self):
        c = Conversation(system_prompt="test", max_tokens=10)
        c.add_user_message("this is a long message that exceeds the token limit")
        assert len(c.messages) == 2

    def test_to_dict(self):
        c = Conversation(system_prompt="You are test.", max_tokens=500)
        c.add_user_message("hi")
        d = c.to_dict()
        assert d["system_prompt"] == "You are test."
        assert len(d["messages"]) == 2
        assert d["max_tokens"] == 500

    def test_from_dict(self):
        c = Conversation.from_dict({
            "system_prompt": "Restored.",
            "messages": [{"role": "system", "content": "Restored."}, {"role": "user", "content": "hello"}],
            "max_tokens": 1000,
        })
        assert c.system_prompt == "Restored."
        assert len(c.messages) == 2
        assert c.messages[1]["content"] == "hello"

    def test_custom_system_prompt(self):
        c = Conversation(system_prompt="Custom.")
        assert c.system_prompt == "Custom."

    def test_default_system_prompt_when_none(self):
        c = Conversation()
        assert len(c.system_prompt) > 0

    def test_summarize_oldest_removes_when_no_llm(self):
        c = Conversation(system_prompt="test")

        async def run():
            c.add_user_message("first exchange")
            c.add_assistant_message("first response")
            c.add_user_message("second exchange")
            c.add_assistant_message("second response")
            await c.summarize_oldest(llm=None)
            assert len(c.messages) == 4

        asyncio.run(run())

    def test_summarize_oldest_skips_when_few_messages(self):
        c = Conversation(system_prompt="test")

        async def run():
            c.add_user_message("only one message")
            await c.summarize_oldest(llm=None)
            assert len(c.messages) == 2

        asyncio.run(run())

    def test_trim_keeps_system_prompt(self):
        c = Conversation(system_prompt="keep", max_tokens=5)
        c.add_user_message("x" * 100)
        assert c.messages[0]["role"] == "system"
        assert c.messages[0]["content"] == "keep"


class TestCreateConversation:
    def test_creates_with_custom_system_prompt(self):
        c = create_conversation(system_prompt="My custom prompt")
        assert c.system_prompt == "My custom prompt"

    def test_creates_with_memory(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            c = create_conversation(system_prompt="test", memory_path=path)
            assert c.memory is not None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_creates_without_memory(self):
        c = create_conversation(system_prompt="test")
        assert c.memory is not None

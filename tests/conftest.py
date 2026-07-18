from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from raven.channels.base import BaseChannel
from raven.core.config import settings
from raven.core.db import Database
from raven.core.gateway.gateway import Gateway
from raven.core.llm import LLMProvider, LLMResponse
from raven.core.models import IncomingMessage, Message
from raven.core.plugin_loader import PluginLoader


class MockLLMProvider(LLMProvider):
    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["Test response"]
        self.call_count = 0

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self.call_count += 1
        idx = min(self.call_count - 1, len(self.responses) - 1)
        return LLMResponse(content=self.responses[idx])

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        self.call_count += 1
        idx = min(self.call_count - 1, len(self.responses) - 1)
        for token in self.responses[idx].split():
            yield token + " "
            await asyncio.sleep(0)

    async def cleanup(self):
        pass


class MockChannel(BaseChannel):
    channel_id = "mock"

    def __init__(self):
        self.sent_messages: list[Message] = []
        self._handler = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send(self, session_id: str, message: Message):
        self.sent_messages.append(message)
        return message

    async def on_message(self, handler):
        self._handler = handler

    async def start(self):
        pass

    async def stop(self):
        pass

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr("raven.core.gateway.gateway.settings.default_model", "ollama/test")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "open")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.context_visibility", "public")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_allow_from", "")


@pytest.fixture
async def real_db(tmp_path) -> AsyncGenerator[Database, None]:
    db = Database(tmp_path / "test.db")
    await db.connect()
    yield db
    await db.disconnect()


@pytest.fixture
async def gateway(real_db: Database, mock_settings: None) -> AsyncGenerator[Gateway, None]:
    g = Gateway(db=real_db, plugin_loader=PluginLoader())
    g.llm._providers["ollama"] = MockLLMProvider(["Test response"])
    channel = MockChannel()
    await g.register_channel(channel)
    channel._handler = g.handle_message
    yield g
    await g.stop()

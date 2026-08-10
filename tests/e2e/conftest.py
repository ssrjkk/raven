from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from raven.channels.base import BaseChannel
from raven.core.gateway.gateway import Gateway
from raven.core.llm import LLMRouter
from raven.core.llm.protocol import LLMResponse
from raven.core.models import IncomingMessage, Message


class MockLLMProvider:
    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["Hello! How can I help you?"]
        self.call_count = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.call_count += 1
        idx = min(self.call_count - 1, len(self.responses) - 1)
        return LLMResponse(content=self.responses[idx], finish_reason="stop")

    async def complete_stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        self.call_count += 1
        idx = min(self.call_count - 1, len(self.responses) - 1)
        for token in self.responses[idx].split():
            yield token + " "
            await asyncio.sleep(0)


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
def mock_db():
    db = AsyncMock()
    db.find_or_create_user = AsyncMock(return_value={"id": "test_user", "is_allowed": True, "role": "user"})
    db.get_or_create_session = AsyncMock(return_value=AsyncMock(id="session_1", channel="mock", user_id="test_user"))
    db.get_session_messages = AsyncMock(return_value=[])
    db.health_check = AsyncMock(return_value=True)
    db.disconnect = AsyncMock()
    db.connect = AsyncMock()
    db.db_path = ":memory:"
    return db


@pytest.fixture
def mock_plugin_loader():
    loader = AsyncMock()
    loader.tools = []
    return loader


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setattr("raven.core.gateway.gateway.settings.default_model", "mock-model")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "open")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.context_visibility", "public")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_allow_from", "")
    return


@pytest.fixture
async def gateway(mock_db, mock_plugin_loader, mock_settings) -> AsyncGenerator[Gateway, None]:
    g = Gateway(db=mock_db, plugin_loader=mock_plugin_loader)
    g.llm = LLMRouter()
    from typing import cast
    g.llm._providers["test"] = cast(Any, MockLLMProvider(["Test response"]))
    channel = MockChannel()
    await g.register_channel(channel)
    channel._handler = g.handle_message
    g._running = True
    yield g
    await g.stop()

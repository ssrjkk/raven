from __future__ import annotations

import pytest

from raven.channels.base import BaseChannel


class _SilentChannel(BaseChannel):
    """A channel that can deliver messages but has no interactive prompt."""

    channel_id = "silent"

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send(self, session_id: str, message: object) -> None: ...

    async def on_message(self, handler: object) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class TestBaseChannel:
    def test_abstract_methods(self):
        methods = ["connect", "disconnect", "send", "on_message", "start", "stop"]
        for m in methods:
            assert hasattr(BaseChannel, m), f"Missing method: {m}"

    def test_channel_id_not_set(self):
        with pytest.raises(TypeError):
            BaseChannel()  # type: ignore[abstract]

    async def test_ask_confirmation_denies_when_the_channel_cannot_ask(self):
        # the inherited default used to answer "yes" on behalf of a user who was never asked
        assert await _SilentChannel().ask_confirmation("u1", "Execute tool 'shell_exec'") is False

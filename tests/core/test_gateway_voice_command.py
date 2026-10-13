from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.gateway.commands.base import CommandContext
from raven.core.gateway.commands.voice import VoiceCommand
from raven.core.models import IncomingMessage


class _FakeTTS:
    def __init__(self, result: str = "out.ogg", exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    def synthesize(self, text: str) -> str:
        if self._exc is not None:
            raise self._exc
        return self._result


def _ctx(*args: str) -> CommandContext:
    event = IncomingMessage(channel="tg", user_id="u1", session_id="tg:chan:u1", text="/voice")
    return CommandContext(event=event, user={}, args=list(args))


def _gateway() -> Any:
    gw = MagicMock()
    gw._send = AsyncMock()
    return gw


@pytest.fixture(autouse=True)
def _no_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.commands.voice.get_policy_for_channel", lambda ch: None)


async def test_access_denied_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.commands.voice.get_policy_for_channel", lambda ch: object())
    monkeypatch.setattr(
        "raven.core.gateway.commands.voice.check_tool_allowed", lambda policy, action, ch: (False, "nope")
    )
    gw = _gateway()
    cmd = VoiceCommand(gw)
    assert await cmd.execute(_ctx("tts", "hi")) is True
    gw._send.assert_awaited_once_with("tg", "tg:chan:u1", "Access denied: nope")


async def test_tts_without_text_shows_usage() -> None:
    gw = _gateway()
    cmd = VoiceCommand(gw)
    assert await cmd.execute(_ctx("tts")) is True
    gw._send.assert_awaited_once_with("tg", "tg:chan:u1", "Usage: /voice tts <text>")


async def test_tts_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.voice.TextToSpeech", lambda: _FakeTTS(result="speech.ogg"))
    gw = _gateway()
    cmd = VoiceCommand(gw)
    assert await cmd.execute(_ctx("tts", "hello", "world")) is True
    gw._send.assert_awaited_once_with("tg", "tg:chan:u1", "🔊 TTS saved to: speech.ogg")


async def test_tts_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.voice.TextToSpeech", lambda: _FakeTTS(exc=RuntimeError("no engine")))
    gw = _gateway()
    cmd = VoiceCommand(gw)
    assert await cmd.execute(_ctx("tts", "hello")) is True
    sent = gw._send.await_args.args[2]
    assert sent == "❌ TTS failed: no engine"


async def test_providers_lists_enum_values() -> None:
    from raven.voice import TTSProvider

    gw = _gateway()
    cmd = VoiceCommand(gw)
    assert await cmd.execute(_ctx("providers")) is True
    sent = gw._send.await_args.args[2]
    assert sent.startswith("🔊 TTS Providers:")
    for p in TTSProvider:
        assert p.value in sent


async def test_no_args_shows_help() -> None:
    gw = _gateway()
    cmd = VoiceCommand(gw)
    assert await cmd.execute(_ctx()) is True
    sent = gw._send.await_args.args[2]
    assert "/voice tts <text>" in sent


async def test_unknown_subcommand_shows_help() -> None:
    gw = _gateway()
    cmd = VoiceCommand(gw)
    assert await cmd.execute(_ctx("bogus")) is True
    assert "Voice commands:" in gw._send.await_args.args[2]

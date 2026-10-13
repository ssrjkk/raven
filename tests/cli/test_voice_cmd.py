from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from raven.cli import voice_cmd
from raven.cli.voice_cmd import voice
from raven.voice.stt import STTProvider
from raven.voice.tts import TTSProvider

_CONVS: list[Any] = []


class _FakeConv:
    def __init__(self, llm_ask: Any, stt_config: Any, tts_config: Any) -> None:
        self.llm_ask = llm_ask
        self.stt_config = stt_config
        self.tts_config = tts_config
        self.wake_mode: bool | None = None
        _CONVS.append(self)

    async def start(self, wake_mode: bool = False) -> None:
        self.wake_mode = wake_mode


class _BoomConv(_FakeConv):
    async def start(self, wake_mode: bool = False) -> None:
        raise KeyboardInterrupt


class _FakeLLM:
    async def complete(self, messages: list[dict[str, str]], model: str | None = None) -> Any:
        return SimpleNamespace(content=f"reply:{messages[0]['content']}:{model}")


@pytest.fixture(autouse=True)
def _wire(monkeypatch: pytest.MonkeyPatch) -> None:
    _CONVS.clear()
    monkeypatch.setattr("importlib.util.find_spec", lambda name: SimpleNamespace())
    monkeypatch.setattr(voice_cmd, "LLMRouter", lambda: _FakeLLM())
    monkeypatch.setattr("raven.voice.conversation.VoiceConversation", _FakeConv)


def _conv() -> Any:
    assert _CONVS
    return _CONVS[0]


def test_missing_sounddevice_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    result = CliRunner().invoke(voice, [])
    assert result.exit_code == 1
    assert "sounddevice not installed" in result.output


def test_defaults_build_configs() -> None:
    result = CliRunner().invoke(voice, [])
    assert result.exit_code == 0, result.output
    conv = _conv()
    assert conv.stt_config.provider == STTProvider.WHISPER
    assert conv.tts_config.provider == TTSProvider.EDGETTS
    assert conv.wake_mode is True


def test_explicit_providers_map() -> None:
    CliRunner().invoke(voice, ["--stt", "google", "--tts", "gtts", "--no-wake"])
    conv = _conv()
    assert conv.stt_config.provider == STTProvider.GOOGLE
    assert conv.tts_config.provider == TTSProvider.GTTS
    assert conv.wake_mode is False


def test_unknown_provider_falls_back_to_default() -> None:
    CliRunner().invoke(voice, ["--stt", "bogus", "--tts", "bogus"])
    conv = _conv()
    assert conv.stt_config.provider == STTProvider.WHISPER
    assert conv.tts_config.provider == TTSProvider.EDGETTS


def test_ghost_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr("raven.core.config.apply_ghost_mode", lambda: called.append("ghost"))
    CliRunner().invoke(voice, ["--ghost"])
    assert called == ["ghost"]
    conv = _conv()
    assert conv.tts_config.provider == TTSProvider.SYSTEM


def test_ask_closure_queries_llm() -> None:
    CliRunner().invoke(voice, ["--model", "gpt-x"])
    conv = _conv()
    out = asyncio.run(conv.llm_ask("hello"))
    assert out == "reply:hello:gpt-x"


def test_keyboard_interrupt_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.voice.conversation.VoiceConversation", _BoomConv)
    result = CliRunner().invoke(voice, [])
    assert result.exit_code == 0
    assert "Voice conversation ended" in result.output

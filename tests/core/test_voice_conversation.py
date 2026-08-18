from __future__ import annotations

import wave
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.voice.conversation import VoiceConversation


def _make_conversation() -> VoiceConversation:
    conv = VoiceConversation.__new__(VoiceConversation)
    conv.stt = MagicMock()
    conv.tts = MagicMock()
    conv.recorder = MagicMock()
    conv.player = MagicMock()
    conv.llm_ask = None
    conv.wake_word = "raven"
    conv._running = False
    return conv


class TestProcessUtterance:
    async def test_transcribes_and_strips(self):
        conv = _make_conversation()
        conv.stt.transcribe = MagicMock(return_value="  hello there  ")  # type: ignore[method-assign]
        result = await conv.process_utterance("audio.wav")
        assert result == "hello there"

    async def test_empty_transcription_returns_none(self):
        conv = _make_conversation()
        conv.stt.transcribe = MagicMock(return_value="")  # type: ignore[method-assign]
        assert await conv.process_utterance("audio.wav") is None

    async def test_stt_error_returns_none(self):
        conv = _make_conversation()
        conv.stt.transcribe = MagicMock(side_effect=RuntimeError("no model"))  # type: ignore[method-assign]
        assert await conv.process_utterance("audio.wav") is None


class TestThinkAndRespond:
    async def test_async_llm(self):
        conv = _make_conversation()
        conv.llm_ask = AsyncMock(return_value="async answer")
        assert await conv.think_and_respond("hi") == "async answer"

    async def test_sync_llm(self):
        conv = _make_conversation()
        conv.llm_ask = lambda text: f"echo:{text}"
        assert await conv.think_and_respond("hello") == "echo:hello"

    async def test_llm_error_returns_apology(self):
        conv = _make_conversation()
        conv.llm_ask = AsyncMock(side_effect=RuntimeError("boom"))
        result = await conv.think_and_respond("hi")
        assert result is not None
        assert "Sorry, I encountered an error" in result
        assert "boom" in result

    async def test_no_llm_echoes(self):
        conv = _make_conversation()
        assert await conv.think_and_respond("ping") == "I heard: ping"


class TestSpeak:
    pass


def _write_wav(path: str) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"\x00\x00" * 100)


@pytest.mark.asyncio
async def test_speak_enqueues_audio_and_deletes_file(tmp_path):
    wav = tmp_path / "out.wav"
    _write_wav(str(wav))
    conv = _make_conversation()
    conv.tts.synthesize = MagicMock(return_value=str(wav))  # type: ignore[method-assign]
    await conv.speak("hello")
    conv.player.enqueue.assert_called_once()  # type: ignore[attr-defined]
    assert not wav.exists()


@pytest.mark.asyncio
async def test_speak_missing_file_is_noop(tmp_path):
    conv = _make_conversation()
    conv.tts.synthesize = MagicMock(return_value=str(tmp_path / "missing.wav"))  # type: ignore[method-assign]
    await conv.speak("hello")
    conv.player.enqueue.assert_not_called()  # type: ignore[attr-defined]


class TestStripWakeWord:
    def test_strips_leading_wake_word(self):
        conv = _make_conversation()
        assert conv._strip_wake_word("raven привет") == "привет"

    def test_case_insensitive_leading(self):
        conv = _make_conversation()
        assert conv._strip_wake_word("RaVeN hello") == "hello"

    def test_keeps_mid_text(self):
        conv = _make_conversation()
        assert conv._strip_wake_word("a raven flies") == "a raven flies"

    def test_keeps_casing_of_rest(self):
        conv = _make_conversation()
        assert conv._strip_wake_word("raven Hello World") == "Hello World"

    def test_wake_word_only_returns_none(self):
        conv = _make_conversation()
        assert conv._strip_wake_word("raven") is None

    def test_no_wake_word_returns_none(self):
        conv = _make_conversation()
        assert conv._strip_wake_word("hello there") is None


class TestAudioPlayerStop:
    def test_stop_playback_clears_queue_and_stops_device(self, monkeypatch: pytest.MonkeyPatch):
        import sys
        from types import ModuleType

        fake_sd = ModuleType("sounddevice")
        fake_sd.stop = MagicMock()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

        from raven.voice.conversation import AudioPlayer

        player = AudioPlayer()
        player.enqueue(b"\x00\x00" * 40)
        assert player._queue.qsize() == 1
        player.stop_playback()
        assert player._queue.qsize() == 0
        fake_sd.stop.assert_called_once()
        assert player.is_playing() is False

    def test_enqueue_keeps_sample_rate_for_worker(self, monkeypatch: pytest.MonkeyPatch):
        import sys
        from types import ModuleType

        fake_sd = ModuleType("sounddevice")
        fake_sd.play = MagicMock()  # type: ignore[attr-defined]
        fake_sd.wait = MagicMock()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

        from raven.voice.conversation import AudioPlayer

        player = AudioPlayer()
        player.enqueue(b"\x00\x00" * 40, sample_rate=16000)
        item = player._queue.get()
        assert item is not None
        data, rate = item
        assert rate == 16000
        assert data.shape[1] == 1

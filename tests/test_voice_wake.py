from __future__ import annotations

import asyncio
import sys
import time
import types
from collections.abc import Callable
from typing import Any

import pytest
from loguru import logger as loguru_logger

import raven.voice.stt as stt_module
import raven.voice.wake as wake
from raven.voice.wake import WAKE_WORDS, WakeWordDetector

REAL_SLEEP = asyncio.sleep


async def _wait_until(cond: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            msg = "condition not met in time"
            raise TimeoutError(msg)
        await REAL_SLEEP(0.01)


def _install_wake_sr(
    monkeypatch: pytest.MonkeyPatch,
    results: list[Any],
    mic_error: OSError | None = None,
    holder: list[Any] | None = None,
) -> dict[str, Any]:
    mod = types.ModuleType("speech_recognition")

    class WaitTimeoutError(Exception):
        pass

    class AudioData:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def get_wav_data(self) -> bytes:
            return self._data

    class Microphone:
        def __init__(self) -> None:
            if mic_error is not None:
                raise mic_error

        def __enter__(self) -> Microphone:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class Recognizer:
        def __init__(self) -> None:
            self.pause_threshold = 0.0

        def adjust_for_ambient_noise(self, source: object, duration: float = 0.5) -> None:
            return None

        def listen(self, source: object, timeout: float = 1, phrase_time_limit: float = 3) -> AudioData:
            state["listen_calls"] += 1
            if results:
                item = results.pop(0)
                if isinstance(item, Exception):
                    raise item
                return AudioData(item)
            if holder:
                holder[0]._running = False
            raise WaitTimeoutError()

    state: dict[str, Any] = {
        "listen_calls": 0,
        "results": results,
        "WaitTimeoutError": WaitTimeoutError,
    }
    mod.Recognizer = Recognizer  # type: ignore[attr-defined]
    mod.Microphone = Microphone  # type: ignore[attr-defined]
    mod.WaitTimeoutError = WaitTimeoutError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "speech_recognition", mod)
    return state


def _install_fake_stt(monkeypatch: pytest.MonkeyPatch, texts: list[str]) -> dict[str, Any]:
    state: dict[str, Any] = {"transcribe_calls": 0, "paths": []}

    class FakeSTT:
        def __init__(self) -> None:
            return None

        def transcribe(self, path: str) -> str:
            state["transcribe_calls"] += 1
            state["paths"].append(path)
            return texts.pop(0) if texts else ""

    monkeypatch.setattr(stt_module, "SpeechToText", FakeSTT)
    return state


class TestWakeWordDetectorInit:
    def test_defaults(self) -> None:
        d = WakeWordDetector()
        assert d.callback is None
        assert not d._running
        assert d._task is None
        assert d.timeout == 5.0
        assert d.silence_threshold == 300

    def test_custom_callback(self) -> None:
        async def cb(text: str) -> str:
            return text

        d = WakeWordDetector(callback=cb)
        assert d.callback is cb

    def test_wake_word_patterns(self) -> None:
        assert "raven" in WAKE_WORDS
        assert "hey raven" in WAKE_WORDS
        assert "ok raven" in WAKE_WORDS
        assert WAKE_WORDS["raven"].search("call raven now") is not None
        assert WAKE_WORDS["hey raven"].search("HEY RAVEN please") is not None
        assert WAKE_WORDS["ok raven"].search("ok raven") is not None
        assert WAKE_WORDS["raven"].search("crawled") is None


class TestStartStop:
    def test_start_stop_import_error(self) -> None:
        async def scenario() -> None:
            d = WakeWordDetector()
            assert not d.is_running()
            await d.start()
            assert d.is_running()
            assert d._task is not None
            await d.stop()
            assert not d.is_running()
            assert d._task is None
            await REAL_SLEEP(0.05)

        asyncio.run(scenario())

    def test_stop_without_start(self) -> None:
        async def scenario() -> None:
            d = WakeWordDetector()
            await d.stop()
            assert not d.is_running()

        asyncio.run(scenario())

    def test_is_running_default(self) -> None:
        d = WakeWordDetector()
        assert not d.is_running()


class TestListenLoop:
    def test_no_microphone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_wake_sr(monkeypatch, [], mic_error=OSError("no mic"))

        async def scenario() -> None:
            d = WakeWordDetector()
            d._running = True
            await d._listen_loop()

        asyncio.run(scenario())

    def test_success_detection_and_empty_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_wake_sr(monkeypatch, [b"wav-empty", b"wav-hey"])
        stt_state = _install_fake_stt(monkeypatch, ["", "hey raven"])
        got: list[str] = []

        async def scenario() -> None:
            d = WakeWordDetector()

            async def cb(text: str) -> None:
                got.append(text)
                d._running = False

            d.callback = cb  # type: ignore[assignment]
            d._running = True
            await d._listen_loop()

        asyncio.run(scenario())
        assert got == ["hey raven"]
        assert stt_state["transcribe_calls"] == 2

    def test_wait_timeout_continue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder: list[Any] = []
        state = _install_wake_sr(monkeypatch, [], holder=holder)
        state["results"].append(state["WaitTimeoutError"]())
        state["results"].append(b"wav-ok")
        stt_state = _install_fake_stt(monkeypatch, ["ok raven"])
        got: list[str] = []

        async def scenario() -> None:
            d = WakeWordDetector()

            async def cb(text: str) -> None:
                got.append(text)
                d._running = False

            d.callback = cb  # type: ignore[assignment]
            d._running = True
            await d._listen_loop()

        asyncio.run(scenario())
        assert got == ["ok raven"]
        assert stt_state["transcribe_calls"] == 1

    def test_no_callback_no_wake_word(self, monkeypatch: pytest.MonkeyPatch) -> None:
        holder: list[Any] = []
        state = _install_wake_sr(monkeypatch, [b"wav"], holder=holder)
        _install_fake_stt(monkeypatch, ["hello world"])
        logs: list[Any] = []
        monkeypatch.setattr(loguru_logger, "exception", lambda *a, **k: logs.append(a))

        async def scenario() -> None:
            d = WakeWordDetector()
            holder.append(d)
            d._running = True
            await d._listen_loop()

        asyncio.run(scenario())
        assert state["listen_calls"] == 2

    def test_callback_exception_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_wake_sr(monkeypatch, [RuntimeError("boom"), b"wav"])
        _install_fake_stt(monkeypatch, ["raven"])
        got: list[str] = []
        logs: list[Any] = []
        monkeypatch.setattr(loguru_logger, "exception", lambda *a, **k: logs.append(a))

        async def scenario() -> None:
            d = WakeWordDetector()

            async def cb(text: str) -> None:
                got.append(text)
                d._running = False

            d.callback = cb  # type: ignore[assignment]
            d._running = True
            await d._listen_loop()

        asyncio.run(scenario())
        assert got == ["raven"]
        assert logs, "logger.exception should have been called"

    def test_cancelled_error_breaks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_wake_sr(monkeypatch, [b"wav"])
        _install_fake_stt(monkeypatch, ["raven"])
        got: list[str] = []

        async def scenario() -> None:
            d = WakeWordDetector()

            async def cb(text: str) -> None:
                got.append(text)
                await asyncio.sleep(60)

            d.callback = cb  # type: ignore[assignment]
            d._running = True
            task = asyncio.create_task(d._listen_loop())
            await _wait_until(lambda: len(got) > 0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        asyncio.run(scenario())
        assert got == ["raven"]

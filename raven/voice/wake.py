from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiofiles
from loguru import logger

WakeCallback = Callable[[str], Awaitable[str]]

WAKE_WORDS = {
    "raven": re.compile(r"\braven\b", re.IGNORECASE),
    "hey raven": re.compile(r"\bhey\s+raven\b", re.IGNORECASE),
    "ok raven": re.compile(r"\bok\s+raven\b", re.IGNORECASE),
}


class WakeWordDetector:
    def __init__(self, callback: WakeCallback | None = None):
        self.callback = callback
        self._running = False
        self._task: asyncio.Task[Any] | None = None
        self.timeout: float = 5.0
        self.silence_threshold: float = 300

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("WakeWordDetector started")

    @staticmethod
    def _capture(mic: Any, recognizer: Any) -> Any:
        with mic as source:
            return recognizer.listen(source, timeout=1, phrase_time_limit=3)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("WakeWordDetector stopped")

    async def _listen_loop(self):
        try:
            import speech_recognition as sr
        except ImportError:
            logger.warning("speech_recognition not installed, wake word detection disabled")
            return

        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 0.8
        try:
            mic = sr.Microphone()
        except OSError:
            logger.warning("No microphone found, wake word detection disabled")
            return

        with mic as source:
            await asyncio.to_thread(recognizer.adjust_for_ambient_noise, source, duration=0.5)

        while self._running:
            try:
                audio = await asyncio.to_thread(self._capture, mic, recognizer)
                temp = Path(tempfile.gettempdir()) / "raven_wake.wav"
                async with aiofiles.open(temp, "wb") as f:
                    await f.write(audio.get_wav_data())

                from raven.voice.stt import SpeechToText

                stt = SpeechToText()
                text = await asyncio.to_thread(stt.transcribe, str(temp))
                await asyncio.to_thread(temp.unlink)

                if not text:
                    continue

                matched = None
                for word, pattern in WAKE_WORDS.items():
                    if pattern.search(text):
                        matched = word
                        break

                if matched:
                    logger.info("Wake word '{}' detected in: {}", matched, text)
                    if self.callback:
                        await self.callback(text)
            except asyncio.CancelledError:
                break
            except sr.WaitTimeoutError:
                continue
            except Exception:
                logger.exception("Wake word detection error")
                await asyncio.sleep(1)

    def is_running(self) -> bool:
        return self._running

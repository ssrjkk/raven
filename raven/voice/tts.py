from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger


class TTSProvider(StrEnum):
    ELEVENLABS = "elevenlabs"
    GTTS = "gtts"
    SYSTEM = "system"
    EDGETTS = "edge"


_ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")


class TTSConfig:
    def __init__(
        self,
        provider: TTSProvider = TTSProvider.SYSTEM,
        voice: str = "",
        model: str = "",
        speed: float = 1.0,
        api_key: str = "",
        cache_dir: str = "",
    ) -> None:
        self.provider = provider
        self.voice = voice
        self.model = model
        self.speed = speed
        self.api_key = api_key or _ELEVENLABS_API_KEY
        self.cache_dir = Path(cache_dir or tempfile.gettempdir()) / "raven_tts_cache"


class TextToSpeech:
    def __init__(self, config: TTSConfig | None = None) -> None:
        self.config = config or TTSConfig()

    def synthesize(self, text: str, output_path: str = "") -> str:
        provider_map = {
            TTSProvider.ELEVENLABS: self._synthesize_elevenlabs,
            TTSProvider.GTTS: self._synthesize_gtts,
            TTSProvider.SYSTEM: self._synthesize_system,
            TTSProvider.EDGETTS: self._synthesize_edge,
        }
        fn = provider_map.get(self.config.provider)
        if not fn:
            raise ValueError(f"Unsupported TTS provider: {self.config.provider}")
        return fn(text, output_path)

    def _synthesize_elevenlabs(self, text: str, output_path: str = "") -> str:
        try:
            from elevenlabs import Voice, generate
        except ImportError:
            logger.warning("elevenlabs not installed, falling back to system TTS")
            return self._synthesize_system(text, output_path)
        if not self.config.api_key:
            logger.warning("ELEVENLABS_API_KEY not set, falling back to system TTS")
            return self._synthesize_system(text, output_path)
        out = output_path or str(self.config.cache_dir / f"{uuid4().hex}.mp3")
        audio = generate(
            text=text,
            voice=Voice(voice_id=self.config.voice or "21m00Tcm4TlvDq8ikWAM"),
            model=self.config.model or "eleven_monolingual_v1",
            api_key=self.config.api_key,
        )
        with open(out, "wb") as f:
            f.write(audio)
        logger.info("ElevenLabs TTS saved to {}", out)
        return out

    def _synthesize_gtts(self, text: str, output_path: str = "") -> str:
        try:
            from gtts import gTTS
        except ImportError:
            logger.warning("gtts not installed, falling back to system TTS")
            return self._synthesize_system(text, output_path)
        out = output_path or str(self.config.cache_dir / f"{uuid4().hex}.mp3")
        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(out)
        logger.info("gTTS TTS saved to {}", out)
        return out

    def _synthesize_system(self, text: str, output_path: str = "") -> str:
        out = output_path or str(self.config.cache_dir / f"{uuid4().hex}.wav")
        if os.name == "nt":
            self._synthesize_windows_sapi(text, out)
        else:
            self._synthesize_macos_say(text, out)
        logger.info("System TTS saved to {}", out)
        return out

    def _synthesize_windows_sapi(self, text: str, output_path: str):
        try:
            import pythoncom

            pythoncom.CoInitialize()
            from win32com.client import Dispatch

            speaker = Dispatch("SAPI.SpVoice")
            stream = Dispatch("SAPI.SpFileStream")
            stream.Open(output_path, 3, False)
            speaker.AudioOutputStream = stream
            speaker.Speak(text)
            stream.Close()
        except ImportError:
            logger.warning("win32com not available, writing silence WAV")
            import struct
            import wave
            sample_rate = 22050
            duration = max(len(text) * 0.06, 1.0)
            num_samples = int(sample_rate * duration)
            with wave.open(output_path, "w") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(struct.pack(f"<{num_samples}h", *([0] * num_samples)))

    def _synthesize_macos_say(self, text: str, output_path: str):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            tmp = f.name
        try:
            subprocess.run(  # noqa: S603
                ["say", "-o", output_path, "-f", tmp],  # noqa: S607
                capture_output=True, timeout=30,
            )
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _synthesize_edge(self, text: str, output_path: str = "") -> str:
        try:
            import edge_tts
        except ImportError:
            logger.warning("edge-tts not installed, falling back to system TTS")
            return self._synthesize_system(text, output_path)

        out = output_path or str(self.config.cache_dir / f"{uuid4().hex}.mp3")
        voice = self.config.voice or "en-US-AriaNeural"
        _loop = asyncio.new_event_loop()
        try:
            _loop.run_until_complete(edge_tts.Communicate(text, voice).save(out))
        finally:
            _loop.close()
        logger.info("Edge TTS saved to {}", out)
        return out

    def list_voices(self) -> list[dict[str, Any]]:
        if self.config.provider == TTSProvider.ELEVENLABS:
            return self._list_elevenlabs_voices()
        if os.name == "nt":
            return [{"id": "windows-sapi", "name": "Windows SAPI (default)"}]
        return [{"id": "macos-say", "name": "macOS say (default)"}]

    def _list_elevenlabs_voices(self) -> list[dict[str, Any]]:
        try:
            from elevenlabs import voices

            return [{"id": v.voice_id, "name": v.name} for v in voices()]
        except ImportError as e:
            logger.debug("elevenlabs voices not available: {}", e)
            return []




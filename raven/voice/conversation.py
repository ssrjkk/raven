from __future__ import annotations

import asyncio
import queue
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger

from raven.voice.stt import SpeechToText, STTConfig, STTProvider
from raven.voice.tts import TextToSpeech, TTSConfig, TTSProvider


class AudioPlayer:
    def __init__(self) -> None:
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._playing = False
        self._stop = False

    def _play_worker(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not installed. Install: pip install sounddevice")
            return
        try:
            while not self._stop:
                data = self._queue.get()
                if data is None:
                    break
                self._playing = True
                sd.play(data, samplerate=24000)
                sd.wait()
                self._playing = False
        except Exception as exc:
            logger.error("Audio playback error: {}", exc)
        finally:
            self._playing = False

    def start(self) -> None:
        self._stop = False
        self._thread = threading.Thread(target=self._play_worker, daemon=True)
        self._thread.start()

    def enqueue(self, audio_data: bytes, sample_rate: int = 24000) -> None:
        data = np.frombuffer(audio_data, dtype=np.int16).reshape(-1, 1)
        self._queue.put(data)

    def stop_playback(self) -> None:
        with self._queue.mutex:
            self._queue.queue.clear()
        self._playing = False

    def is_playing(self) -> bool:
        return self._playing

    def close(self) -> None:
        self._stop = True
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)


class VoiceRecorder:
    def __init__(
        self, sample_rate: int = 16000, chunk_sec: float = 0.5, silence_sec: float = 1.5, energy_threshold: float = 500
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_sec)
        self.silence_chunks = int(silence_sec / chunk_sec)
        self.energy_threshold = energy_threshold
        self._running = False

    def _get_energy(self, data: bytes) -> float:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(samples**2)))

    def record_utterance(self, timeout: float = 30.0) -> bytes | None:
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not installed. Install: pip install sounddevice")
            return None
        logger.info("Listening... (speak now)")
        recorded: list[bytes] = []
        silence_count = 0
        started = False
        start_time = time.time()
        try:
            with sd.RawInputStream(
                samplerate=self.sample_rate, blocksize=self.chunk_size, channels=1, dtype="int16"
            ) as stream:
                while time.time() - start_time < timeout:
                    data, _ = stream.read(self.chunk_size)
                    energy = self._get_energy(data)
                    if energy > self.energy_threshold:
                        if not started:
                            logger.debug("Voice detected")
                            started = True
                        recorded.append(bytes(data))
                        silence_count = 0
                    elif started:
                        silence_count += 1
                        recorded.append(bytes(data))
                        if silence_count >= self.silence_chunks:
                            logger.debug("Silence detected, stopping")
                            break
                    if not started and time.time() - start_time > 2:
                        logger.debug("No voice detected yet...")
        except KeyboardInterrupt:
            logger.info("Recording cancelled")
            return None
        except Exception as exc:
            logger.error("Recording error: {}", exc)
            return None
        if not recorded:
            logger.info("Nothing recorded")
            return None
        result = b"".join(recorded)
        duration = len(result) / (self.sample_rate * 2)
        logger.info("Recorded {:.1f}s of audio", duration)
        return result

    def save_to_temp(self, audio_data: bytes) -> str:
        import wave

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp, wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data)
        return tmp.name


class VoiceConversation:
    def __init__(
        self,
        llm_ask: Any = None,
        stt_config: STTConfig | None = None,
        tts_config: TTSConfig | None = None,
        wake_word: str = "raven",
    ) -> None:
        from raven.core.config import get_settings

        stt_provider = STTProvider.WHISPER
        tts_provider = TTSProvider.SYSTEM if get_settings().ghost_mode else TTSProvider.EDGETTS
        self.stt = SpeechToText(stt_config or STTConfig(provider=stt_provider))
        self.tts = TextToSpeech(tts_config or TTSConfig(provider=tts_provider))
        self.recorder = VoiceRecorder()
        self.player = AudioPlayer()
        self.llm_ask = llm_ask
        self.wake_word = wake_word.lower()
        self._running = False

    async def speak(self, text: str) -> None:
        logger.info("TTS: {}", text[:100])
        try:
            audio_file = await asyncio.to_thread(self.tts.synthesize, text)
            if audio_file and Path(audio_file).exists():
                import wave

                def _read_wave(filepath: str) -> tuple[bytes, int]:
                    with wave.open(filepath, "rb") as wf:
                        frames = wf.readframes(wf.getnframes())
                        return frames, wf.getframerate()

                frames, sr = await asyncio.to_thread(_read_wave, audio_file)
                data = np.frombuffer(frames, dtype=np.int16).reshape(-1, 1)
                self.player.enqueue(data.tobytes(), sample_rate=int(sr))
                await asyncio.to_thread(Path(audio_file).unlink, missing_ok=True)
        except Exception as exc:
            logger.warning("TTS playback failed: {}", exc)

    async def process_utterance(self, audio_path: str) -> str | None:
        logger.info("Transcribing...")
        try:
            text = await asyncio.to_thread(self.stt.transcribe, audio_path)
            text = text.strip()
            if text:
                logger.info("You: {}", text)
            return text or None
        except Exception as exc:
            logger.error("STT error: {}", exc)
            return None

    async def think_and_respond(self, text: str) -> str | None:
        if self.llm_ask is None:
            return f"I heard: {text}"
        try:
            if asyncio.iscoroutinefunction(self.llm_ask):
                response = await self.llm_ask(text)
            else:
                response = await asyncio.to_thread(self.llm_ask, text)
            result = str(response)[:500]
            logger.info("Raven: {}", result[:100])
            return result
        except Exception as exc:
            logger.error("LLM error: {}", exc)
            return f"Sorry, I encountered an error: {exc}"

    async def start(self, wake_mode: bool = True) -> None:
        self._running = True
        self.player.start()
        logger.info("Voice conversation started (Ctrl+C to stop)")
        if wake_mode:
            logger.info("Wake word: '{}'", self.wake_word)
        else:
            logger.info("Continuous mode: speak freely")
        try:
            while self._running:
                audio_data = await asyncio.to_thread(self.recorder.record_utterance)
                if audio_data is None:
                    if self._running:
                        continue
                    break
                audio_path = self.recorder.save_to_temp(audio_data)
                text = await self.process_utterance(audio_path)
                Path(audio_path).unlink(missing_ok=True)
                if not text:
                    continue
                if wake_mode and self.wake_word not in text.lower():
                    logger.debug("Wake word not found in: {}", text)
                    continue
                if wake_mode:
                    text = text.lower().replace(self.wake_word, "", 1).strip()
                    if not text:
                        continue
                self.player.stop_playback()
                response = await self.think_and_respond(text)
                if response:
                    await self.speak(response)
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        self.player.close()

    async def __aenter__(self) -> VoiceConversation:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.stop()

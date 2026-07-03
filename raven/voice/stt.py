from __future__ import annotations

import contextlib
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger


class STTProvider(StrEnum):
    WHISPER = "whisper"
    GOOGLE = "google"
    AZURE = "azure"
    VOSK = "vosk"


class STTConfig:
    def __init__(
        self,
        provider: STTProvider = STTProvider.WHISPER,
        model: str = "base",
        language: str = "en",
        api_key: str = "",
        region: str = "",
    ):
        self.provider = provider
        self.model = model
        self.language = language
        self.api_key = api_key
        self.region = region


class SpeechToText:
    def __init__(self, config: STTConfig | None = None):
        self.config = config or STTConfig()

    def transcribe(self, audio_path: str, **kwargs: Any) -> str:
        provider_map = {
            STTProvider.WHISPER: self._transcribe_whisper,
            STTProvider.GOOGLE: self._transcribe_google,
            STTProvider.AZURE: self._transcribe_azure,
            STTProvider.VOSK: self._transcribe_vosk,
        }
        fn = provider_map.get(self.config.provider)
        if not fn:
            raise ValueError(f"Unsupported STT provider: {self.config.provider}")
        return fn(audio_path, **kwargs)

    def _transcribe_whisper(self, audio_path: str, **kwargs: Any) -> str:
        try:
            import whisper
        except ImportError:
            logger.warning("openai-whisper not installed")
            return ""
        model_name = kwargs.get("model", self.config.model)
        model = whisper.load_model(model_name)
        result = model.transcribe(audio_path, language=self.config.language)
        text: str = result.get("text", "").strip()
        logger.info("Whisper transcription ({} chars): {}", len(text), text[:80])
        return text

    def _transcribe_google(self, audio_path: str, **kwargs: Any) -> str:
        try:
            import speech_recognition as sr
        except ImportError:
            logger.warning("speech_recognition not installed")
            return ""
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_path) as source:
            audio = recognizer.record(source)
        try:
            text: str = recognizer.recognize_google(audio, language=self.config.language)
            logger.info("Google STT ({} chars): {}", len(text), text[:80])
            return text
        except sr.UnknownValueError:
            logger.warning("Google STT could not understand audio")
            return ""
        except sr.RequestError as e:
            logger.error("Google STT error: {}", e)
            return ""

    def _transcribe_azure(self, audio_path: str, **kwargs: Any) -> str:
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError:
            logger.warning("azure-cognitiveservices-speech not installed")
            return ""
        key = self.config.api_key or os.getenv("AZURE_SPEECH_KEY", "")
        region = self.config.region or os.getenv("AZURE_SPEECH_REGION", "")
        if not key or not region:
            logger.warning("Azure Speech key/region not configured")
            return ""
        config = speechsdk.SpeechConfig(subscription=key, region=region)
        audio_input = speechsdk.AudioConfig(filename=audio_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=config, audio_config=audio_input)
        result = recognizer.recognize_once()
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            text: str = result.text.strip()
            logger.info("Azure STT ({} chars): {}", len(text), text[:80])
            return text
        logger.warning("Azure STT failed: {}", result.reason)
        return ""

    def _transcribe_vosk(self, audio_path: str, **kwargs: Any) -> str:
        try:
            import json
            import wave

            import vosk
        except ImportError:
            logger.warning("vosk not installed")
            return ""
        model_path = kwargs.get("model_path", "")
        if not model_path:
            model = vosk.Model(lang=self.config.language)
        else:
            model = vosk.Model(model_path)
        with wave.open(audio_path, "rb") as wf:
            rec = vosk.KaldiRecognizer(model, wf.getframerate())
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                rec.AcceptWaveform(data)
        result = json.loads(rec.FinalResult())
        text: str = result.get("text", "").strip()
        logger.info("Vosk transcription ({} chars): {}", len(text), text[:80])
        return text

    def record_from_microphone(self, duration: float = 5.0) -> str:
        try:
            import speech_recognition as sr
        except ImportError:
            logger.warning("speech_recognition not installed")
            return ""
        temp = Path(tempfile.gettempdir()) / f"raven_recording_{uuid4().hex}.wav"
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            logger.info("Recording for {}s...", duration)
            audio = recognizer.record(source, duration=duration)
        with open(temp, "wb") as f:
            f.write(audio.get_wav_data())
        text = self.transcribe(str(temp))
        with contextlib.suppress(OSError):
            os.unlink(str(temp))
        return text




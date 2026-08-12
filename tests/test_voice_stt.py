from __future__ import annotations

import json
import sys
import tempfile
import types
import wave
from pathlib import Path
from typing import Any

import pytest

import raven.voice.stt as stt
from raven.voice.stt import SpeechToText, STTConfig, STTProvider


def _install_fake_sr(
    monkeypatch: pytest.MonkeyPatch,
    recognize_google_result: Any = "hello google",
    record_wav: bytes = b"RIFF-record",
    listen_wav: bytes = b"RIFF-listen",
) -> dict[str, Any]:
    mod = types.ModuleType("speech_recognition")
    state: dict[str, Any] = {"recognize_languages": [], "recognize_calls": 0}

    class UnknownValueError(Exception):
        pass

    class RequestError(Exception):
        pass

    class AudioData:
        def get_wav_data(self) -> bytes:
            return record_wav if record_wav is not None else listen_wav

    class AudioFile:
        def __init__(self, path: str) -> None:
            state["audio_file_path"] = path

        def __enter__(self) -> AudioFile:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class Microphone:
        def __init__(self) -> None:
            state["mic_created"] = True

        def __enter__(self) -> Microphone:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class Recognizer:
        def __init__(self) -> None:
            self.pause_threshold = 0.8

        def record(self, source: object, duration: float = 0.0) -> AudioData:
            state["record_calls"] = state.get("record_calls", 0) + 1
            return AudioData()

        def recognize_google(self, audio: object, language: str = "en") -> str:
            state["recognize_calls"] += 1
            state["recognize_languages"].append(language)
            if isinstance(recognize_google_result, Exception):
                raise recognize_google_result
            return str(recognize_google_result)

        def listen(self, source: object, timeout: float = 0.0, phrase_time_limit: float = 0.0) -> AudioData:
            return AudioData()

    mod.UnknownValueError = UnknownValueError  # type: ignore[attr-defined]
    mod.RequestError = RequestError  # type: ignore[attr-defined]
    mod.AudioFile = AudioFile  # type: ignore[attr-defined]
    mod.Microphone = Microphone  # type: ignore[attr-defined]
    mod.Recognizer = Recognizer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "speech_recognition", mod)
    return state


def _install_fake_whisper(monkeypatch: pytest.MonkeyPatch, result_text: str) -> dict[str, Any]:
    mod = types.ModuleType("whisper")
    state: dict[str, Any] = {}

    class Model:
        def transcribe(self, path: str, language: str = "en") -> dict[str, Any]:
            state["transcribed_path"] = path
            state["language"] = language
            return {"text": f"  {result_text}  "}

    def load_model(model_name: str) -> Model:
        state["model_name"] = model_name
        return Model()

    mod.load_model = load_model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "whisper", mod)
    return state


def _install_fake_azure(
    monkeypatch: pytest.MonkeyPatch, result_reason: str = "RecognizedSpeech", result_text: str = "hello azure"
) -> dict[str, Any]:
    azure = types.ModuleType("azure")
    azure.__path__ = []
    cogs = types.ModuleType("azure.cognitiveservices")
    cogs.__path__ = []
    speech = types.ModuleType("azure.cognitiveservices.speech")
    state: dict[str, Any] = {}

    class ResultReason:
        RecognizedSpeech = "RecognizedSpeech"
        NoMatch = "NoMatch"

    class SpeechConfig:
        def __init__(self, subscription: str, region: str) -> None:
            state["subscription"] = subscription
            state["region"] = region

    class AudioConfig:
        def __init__(self, filename: str) -> None:
            state["filename"] = filename

    class Result:
        reason = result_reason
        text = result_text

    class SpeechRecognizer:
        def __init__(self, speech_config: object, audio_config: object) -> None:
            state["recognizer_created"] = True

        def recognize_once(self) -> Result:
            return Result()

    speech.ResultReason = ResultReason  # type: ignore[attr-defined]
    speech.SpeechConfig = SpeechConfig  # type: ignore[attr-defined]
    speech.AudioConfig = AudioConfig  # type: ignore[attr-defined]
    speech.SpeechRecognizer = SpeechRecognizer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.cognitiveservices", cogs)
    monkeypatch.setitem(sys.modules, "azure.cognitiveservices.speech", speech)
    return state


def _install_fake_vosk(monkeypatch: pytest.MonkeyPatch, final_text: str = "hello vosk") -> dict[str, Any]:
    mod = types.ModuleType("vosk")
    state: dict[str, Any] = {}

    class Model:
        def __init__(self, *args: object, **kwargs: object) -> None:
            if args:
                state["model_path"] = str(args[0])
            state["model_lang"] = kwargs.get("lang")

    class KaldiRecognizer:
        def __init__(self, model: Model, framerate: int) -> None:
            state["framerate"] = framerate
            self._frames = 0

        def AcceptWaveform(self, data: bytes) -> bool:
            self._frames += 1
            return True

        def FinalResult(self) -> str:
            return json.dumps({"text": final_text})

    mod.Model = Model  # type: ignore[attr-defined]
    mod.KaldiRecognizer = KaldiRecognizer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vosk", mod)
    return state


def _make_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 200)


class TestSTTConfig:
    def test_defaults(self) -> None:
        cfg = STTConfig()
        assert cfg.provider == STTProvider.WHISPER
        assert cfg.model == "base"
        assert cfg.language == "en"
        assert cfg.api_key == ""
        assert cfg.region == ""

    def test_custom_values(self) -> None:
        cfg = STTConfig(provider=STTProvider.AZURE, model="large", language="fr", api_key="k", region="r")
        assert cfg.provider == STTProvider.AZURE
        assert cfg.model == "large"
        assert cfg.language == "fr"
        assert cfg.api_key == "k"
        assert cfg.region == "r"


class TestSpeechToTextInit:
    def test_default_config(self) -> None:
        stt_obj = SpeechToText()
        assert isinstance(stt_obj.config, STTConfig)

    def test_custom_config(self) -> None:
        cfg = STTConfig(provider=STTProvider.GOOGLE)
        stt_obj = SpeechToText(cfg)
        assert stt_obj.config is cfg


class TestTranscribeDispatch:
    @pytest.mark.parametrize(
        ("provider", "method"),
        [
            (STTProvider.WHISPER, "_transcribe_whisper"),
            (STTProvider.GOOGLE, "_transcribe_google"),
            (STTProvider.AZURE, "_transcribe_azure"),
            (STTProvider.VOSK, "_transcribe_vosk"),
        ],
    )
    def test_dispatch(self, monkeypatch: pytest.MonkeyPatch, provider: STTProvider, method: str) -> None:
        stt_obj = SpeechToText(STTConfig(provider=provider))
        calls: dict[str, Any] = {}

        def fake(*args: object, **kwargs: object) -> str:
            calls["args"] = args
            calls["kwargs"] = kwargs
            return "result"

        monkeypatch.setattr(stt_obj, method, fake)
        assert stt_obj.transcribe("audio.wav", extra=1) == "result"
        assert calls["args"] == ("audio.wav",)
        assert calls["kwargs"] == {"extra": 1}

    def test_unsupported_provider(self) -> None:
        stt_obj = SpeechToText(STTConfig(provider="bogus"))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unsupported STT provider"):
            stt_obj.transcribe("audio.wav")


class TestTranscribeWhisper:
    def test_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "whisper", raising=False)
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.WHISPER))
        assert stt_obj._transcribe_whisper("audio.wav") == ""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_whisper(monkeypatch, "hello whisper")
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.WHISPER))
        out = stt_obj._transcribe_whisper("audio.wav")
        assert out == "hello whisper"
        assert state["model_name"] == "base"
        assert state["transcribed_path"] == "audio.wav"
        assert state["language"] == "en"

    def test_custom_model_kwarg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_whisper(monkeypatch, "hello")
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.WHISPER, model="small"))
        stt_obj._transcribe_whisper("audio.wav", model="large")
        assert state["model_name"] == "large"


class TestTranscribeGoogle:
    def test_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "speech_recognition", raising=False)
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.GOOGLE))
        assert stt_obj._transcribe_google("audio.wav") == ""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_sr(monkeypatch, recognize_google_result="hello google")
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.GOOGLE, language="fr"))
        assert stt_obj._transcribe_google("audio.wav") == "hello google"
        assert state["audio_file_path"] == "audio.wav"
        assert state["recognize_languages"] == ["fr"]

    def test_unknown_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sr(monkeypatch, recognize_google_result=None)
        mod = sys.modules["speech_recognition"]

        class Recognizer:
            def record(self, source: object) -> object:
                return object()

            def recognize_google(self, audio: object, language: str = "en") -> str:
                raise mod.UnknownValueError()

        mod.Recognizer = Recognizer  # type: ignore[attr-defined]
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.GOOGLE))
        assert stt_obj._transcribe_google("audio.wav") == ""

    def test_request_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sr(monkeypatch, recognize_google_result=None)
        mod = sys.modules["speech_recognition"]

        class Recognizer:
            def record(self, source: object) -> object:
                return object()

            def recognize_google(self, audio: object, language: str = "en") -> str:
                raise mod.RequestError("boom")

        mod.Recognizer = Recognizer  # type: ignore[attr-defined]
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.GOOGLE))
        assert stt_obj._transcribe_google("audio.wav") == ""


class TestTranscribeAzure:
    def test_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "azure", raising=False)
        monkeypatch.delitem(sys.modules, "azure.cognitiveservices", raising=False)
        monkeypatch.delitem(sys.modules, "azure.cognitiveservices.speech", raising=False)
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.AZURE))
        assert stt_obj._transcribe_azure("audio.wav") == ""

    def test_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_azure(monkeypatch)
        monkeypatch.setattr(stt, "_AZURE_SPEECH_KEY", "")
        monkeypatch.setattr(stt, "_AZURE_SPEECH_REGION", "")
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.AZURE, api_key="", region=""))
        assert stt_obj._transcribe_azure("audio.wav") == ""

    def test_no_region(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_azure(monkeypatch)
        monkeypatch.setattr(stt, "_AZURE_SPEECH_KEY", "")
        monkeypatch.setattr(stt, "_AZURE_SPEECH_REGION", "")
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.AZURE, api_key="key"))
        assert stt_obj._transcribe_azure("audio.wav") == ""

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_azure(monkeypatch, result_reason="RecognizedSpeech", result_text="hello azure")
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.AZURE, api_key="key", region="eastus"))
        assert stt_obj._transcribe_azure("audio.wav") == "hello azure"
        assert state["subscription"] == "key"
        assert state["region"] == "eastus"
        assert state["filename"] == "audio.wav"

    def test_not_recognized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_azure(monkeypatch, result_reason="NoMatch", result_text="")
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.AZURE, api_key="key", region="eastus"))
        assert stt_obj._transcribe_azure("audio.wav") == ""


class TestTranscribeVosk:
    def test_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "vosk", raising=False)
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.VOSK))
        assert stt_obj._transcribe_vosk("audio.wav") == ""

    def test_success_default_model(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_vosk(monkeypatch, "hello vosk")
        wav = tmp_path / "audio.wav"
        _make_wav(wav)
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.VOSK, language="en"))
        assert stt_obj._transcribe_vosk(str(wav)) == "hello vosk"
        assert state["model_lang"] == "en"
        assert state.get("model_path") is None
        assert state["framerate"] == 16000

    def test_success_custom_model_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_vosk(monkeypatch, "custom")
        wav = tmp_path / "audio.wav"
        _make_wav(wav)
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        stt_obj = SpeechToText(STTConfig(provider=STTProvider.VOSK))
        assert stt_obj._transcribe_vosk(str(wav), model_path=str(model_dir)) == "custom"
        assert state["model_path"] == str(model_dir)
        assert state["model_lang"] is None


class TestRecordFromMicrophone:
    def test_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "speech_recognition", raising=False)
        stt_obj = SpeechToText()
        assert stt_obj.record_from_microphone() == ""

    def test_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sr(monkeypatch, record_wav=b"RIFF-wav-data")
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        stt_obj = SpeechToText()
        monkeypatch.setattr(stt_obj, "transcribe", lambda path: f"transcribed:{Path(path).name}")
        out = stt_obj.record_from_microphone(duration=2.0)
        assert out.startswith("transcribed:raven_recording_")
        assert list(tmp_path.iterdir()) == []

    def test_unlink_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_sr(monkeypatch, record_wav=b"RIFF-wav-data")
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

        def _raise_oserror(self: object, *args: object, **kwargs: object) -> None:
            msg = "already gone"
            raise OSError(msg)

        monkeypatch.setattr(Path, "unlink", _raise_oserror)
        stt_obj = SpeechToText()
        monkeypatch.setattr(stt_obj, "transcribe", lambda path: "text")
        assert stt_obj.record_from_microphone(duration=1.0) == "text"
        leftovers = list(tmp_path.iterdir())
        assert len(leftovers) == 1
        assert leftovers[0].name.startswith("raven_recording_")

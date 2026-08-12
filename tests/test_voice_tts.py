from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
import wave
from pathlib import Path
from typing import Any

import pytest

import raven.voice.tts as tts
from raven.voice.tts import TextToSpeech, TTSConfig, TTSProvider


def _install_fake_elevenlabs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    mod = types.ModuleType("elevenlabs")
    state: dict[str, Any] = {}

    class Voice:
        def __init__(self, voice_id: str | None = None, **kwargs: object) -> None:
            self.voice_id = voice_id
            state["voice_id"] = voice_id

    def generate(**kwargs: object) -> bytes:
        state["generate_kwargs"] = kwargs
        return b"\x00\x01\x02mp3"

    def voices() -> list[types.SimpleNamespace]:
        return [types.SimpleNamespace(voice_id="v1", name="Voice One"), types.SimpleNamespace(voice_id="v2", name="Voice Two")]

    mod.Voice = Voice  # type: ignore[attr-defined]
    mod.generate = generate  # type: ignore[attr-defined]
    mod.voices = voices  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "elevenlabs", mod)
    return state


def _install_fake_gtts(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    mod = types.ModuleType("gtts")
    state: dict[str, Any] = {}

    class gTTS:
        def __init__(self, **kwargs: object) -> None:
            state["kwargs"] = kwargs

        def save(self, out: str) -> None:
            state["out"] = out
            Path(out).write_bytes(b"mp3data")

    mod.gTTS = gTTS  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gtts", mod)
    return state


def _install_fake_edge_tts(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    mod = types.ModuleType("edge_tts")
    state: dict[str, Any] = {}

    class Communicate:
        def __init__(self, text: str, voice: str) -> None:
            state["text"] = text
            state["voice"] = voice

        async def save(self, out: str) -> None:
            state["out"] = out
            Path(out).write_bytes(b"edge-data")

    mod.Communicate = Communicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    return state


def _make_fake_sapi(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], list[Any]]:
    import pythoncom
    import win32com.client

    all_instances: list[Any] = []
    state: dict[str, Any] = {"dispatch_calls": []}

    class _FakeSapi:
        def __init__(self) -> None:
            self.events: list[tuple[str, object]] = []
            self.audio_output_stream: object = None
            all_instances.append(self)

        def Open(self, path: str, mode: int, fmt: bool) -> None:
            self.events.append(("open", path))

        def Close(self) -> None:
            self.events.append(("close", None))

        def Speak(self, text: str) -> None:
            self.events.append(("speak", text))

        @property
        def AudioOutputStream(self) -> object:
            return self.audio_output_stream

        @AudioOutputStream.setter
        def AudioOutputStream(self, value: object) -> None:
            self.audio_output_stream = value

    def fake_dispatch(prog_id: str) -> _FakeSapi:
        state["dispatch_calls"].append(prog_id)
        return _FakeSapi()

    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(win32com.client, "Dispatch", fake_dispatch)
    return state, all_instances


class TestTTSConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tts, "_ELEVENLABS_API_KEY", "")
        cfg = TTSConfig()
        assert cfg.provider == TTSProvider.SYSTEM
        assert cfg.voice == ""
        assert cfg.model == ""
        assert cfg.speed == 1.0
        assert cfg.api_key == ""
        assert cfg.cache_dir.name == "raven_tts_cache"

    def test_custom(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tts, "_ELEVENLABS_API_KEY", "")
        cache = tmp_path / "my_cache"
        cfg = TTSConfig(provider=TTSProvider.ELEVENLABS, voice="v", model="m", speed=1.5, api_key="k", cache_dir=str(cache))
        assert cfg.provider == TTSProvider.ELEVENLABS
        assert cfg.voice == "v"
        assert cfg.model == "m"
        assert cfg.speed == 1.5
        assert cfg.api_key == "k"
        assert cfg.cache_dir == cache
        assert cache.exists()

    def test_cache_dir_created(self, tmp_path: Path) -> None:
        cache = tmp_path / "nested" / "cache"
        TTSConfig(cache_dir=str(cache))
        assert cache.is_dir()

    def test_mkdir_oserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_oserror(self: object, *args: object, **kwargs: object) -> None:
            msg = "no space"
            raise OSError(msg)

        monkeypatch.setattr(Path, "mkdir", _raise_oserror)
        cfg = TTSConfig(cache_dir=str(tmp_path / "cache"))
        assert cfg.cache_dir == tmp_path / "cache"


class TestTextToSpeechInit:
    def test_default_config(self) -> None:
        tts_obj = TextToSpeech()
        assert isinstance(tts_obj.config, TTSConfig)

    def test_custom_config(self) -> None:
        cfg = TTSConfig(provider=TTSProvider.GTTS)
        tts_obj = TextToSpeech(cfg)
        assert tts_obj.config is cfg


class TestSynthesizeDispatch:
    @pytest.mark.parametrize(
        ("provider", "method"),
        [
            (TTSProvider.ELEVENLABS, "_synthesize_elevenlabs"),
            (TTSProvider.GTTS, "_synthesize_gtts"),
            (TTSProvider.SYSTEM, "_synthesize_system"),
            (TTSProvider.EDGETTS, "_synthesize_edge"),
        ],
    )
    def test_dispatch(self, monkeypatch: pytest.MonkeyPatch, provider: TTSProvider, method: str) -> None:
        tts_obj = TextToSpeech(TTSConfig(provider=provider))
        calls: dict[str, Any] = {}

        def fake(text: str, output_path: str) -> str:
            calls["text"] = text
            calls["output_path"] = output_path
            return "out.wav"

        monkeypatch.setattr(tts_obj, method, fake)
        assert tts_obj.synthesize("hello") == "out.wav"
        assert calls == {"text": "hello", "output_path": ""}

    def test_unsupported_provider(self) -> None:
        tts_obj = TextToSpeech(TTSConfig(provider="bogus"))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Unsupported TTS provider"):
            tts_obj.synthesize("hello")


class TestSynthesizeElevenlabs:
    def test_import_error_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "elevenlabs", raising=False)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.ELEVENLABS, api_key="k"))
        monkeypatch.setattr(tts_obj, "_synthesize_system", lambda text, output_path: "system-out")
        assert tts_obj._synthesize_elevenlabs("hello") == "system-out"

    def test_no_api_key_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_elevenlabs(monkeypatch)
        monkeypatch.setattr(tts, "_ELEVENLABS_API_KEY", "")
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.ELEVENLABS, api_key=""))
        monkeypatch.setattr(tts_obj, "_synthesize_system", lambda text, output_path: "system-out")
        assert tts_obj._synthesize_elevenlabs("hello") == "system-out"

    def test_success_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_elevenlabs(monkeypatch)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.ELEVENLABS, api_key="k", cache_dir=str(tmp_path)))
        out = tts_obj._synthesize_elevenlabs("hello")
        assert Path(out).read_bytes() == b"\x00\x01\x02mp3"
        assert out.startswith(str(tmp_path))
        assert state["voice_id"] == "21m00Tcm4TlvDq8ikWAM"
        kw = state["generate_kwargs"]
        assert kw["text"] == "hello"
        assert kw["model"] == "eleven_monolingual_v1"
        assert kw["api_key"] == "k"

    def test_success_custom_voice_and_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_elevenlabs(monkeypatch)
        out = tmp_path / "custom.mp3"
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.ELEVENLABS, api_key="k", voice="myv", model="m1", cache_dir=str(tmp_path)))
        result = tts_obj._synthesize_elevenlabs("hello", output_path=str(out))
        assert result == str(out)
        assert out.exists()
        assert state["voice_id"] == "myv"
        assert state["generate_kwargs"]["model"] == "m1"


class TestSynthesizeGtts:
    def test_import_error_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "gtts", raising=False)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.GTTS))
        monkeypatch.setattr(tts_obj, "_synthesize_system", lambda text, output_path: "system-out")
        assert tts_obj._synthesize_gtts("hello") == "system-out"

    def test_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_gtts(monkeypatch)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.GTTS, cache_dir=str(tmp_path)))
        out = tts_obj._synthesize_gtts("hello")
        assert Path(out).read_bytes() == b"mp3data"
        assert state["kwargs"] == {"text": "hello", "lang": "en", "slow": False}
        assert state["out"] == out

    def test_success_custom_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_gtts(monkeypatch)
        out = tmp_path / "custom.mp3"
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.GTTS, cache_dir=str(tmp_path)))
        assert tts_obj._synthesize_gtts("hello", output_path=str(out)) == str(out)


class TestSynthesizeSystem:
    def test_windows_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        tts_obj = TextToSpeech(TTSConfig())
        calls: dict[str, Any] = {}
        monkeypatch.setattr(tts_obj, "_synthesize_windows_sapi", lambda text, output_path: calls.update(text=text, output_path=output_path))
        out = tts_obj._synthesize_system("hello")
        assert calls == {"text": "hello", "output_path": out}
        assert out.endswith(".wav")

    @pytest.mark.skipif(os.name == "nt", reason="POSIX branch requires a POSIX platform")
    def test_posix_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        tts_obj = TextToSpeech(TTSConfig())
        calls: dict[str, Any] = {}
        monkeypatch.setattr(tts_obj, "_synthesize_macos_say", lambda text, output_path: calls.update(text=text, output_path=output_path))
        out = tts_obj._synthesize_system("hello")
        assert calls == {"text": "hello", "output_path": out}

    def test_windows_with_custom_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        out = tmp_path / "speech.wav"
        tts_obj = TextToSpeech(TTSConfig())
        monkeypatch.setattr(tts_obj, "_synthesize_windows_sapi", lambda text, output_path: None)
        assert tts_obj._synthesize_system("hello", output_path=str(out)) == str(out)


class TestSynthesizeWindowsSapi:
    def test_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state, instances = _make_fake_sapi(monkeypatch)
        out = tmp_path / "speech.wav"
        tts_obj = TextToSpeech(TTSConfig())
        tts_obj._synthesize_windows_sapi("hello", str(out))
        assert state["dispatch_calls"] == ["SAPI.SpVoice", "SAPI.SpFileStream"]
        assert len(instances) == 2
        assert instances[0].events == [("speak", "hello")]
        assert instances[1].events == [("open", str(out)), ("close", None)]
        assert instances[0].audio_output_stream is instances[1]

    def test_import_error_writes_silence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def _block(name: str, *args: object, **kwargs: object) -> object:
            if name in ("pythoncom", "win32com", "win32com.client"):
                msg = "blocked"
                raise ImportError(msg)
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", _block)
        out = tmp_path / "silence.wav"
        tts_obj = TextToSpeech(TTSConfig())
        tts_obj._synthesize_windows_sapi("hello", str(out))
        assert out.exists()
        with wave.open(str(out), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 22050

    def test_dispatch_error_writes_silence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import win32com.client

        def _boom(prog_id: str) -> object:
            msg = "SAPI unavailable"
            raise RuntimeError(msg)

        monkeypatch.setattr(win32com.client, "Dispatch", _boom)
        out = tmp_path / "silence.wav"
        tts_obj = TextToSpeech(TTSConfig())
        tts_obj._synthesize_windows_sapi("hello", str(out))
        assert out.exists()
        assert out.stat().st_size > 0


class TestSynthesizeMacosSay:
    def test_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: dict[str, Any] = {}

        def fake_run(args: list[str], *a: object, **kw: object) -> subprocess.CompletedProcess[bytes]:
            calls["args"] = args
            return subprocess.CompletedProcess(args, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        out = tmp_path / "speech.aiff"
        tts_obj = TextToSpeech(TTSConfig())
        tts_obj._synthesize_macos_say("hello", str(out))
        assert calls["args"][0] == "say"
        assert calls["args"][1:3] == ["-o", str(out)]
        tmp_txt = calls["args"][4]
        assert not Path(tmp_txt).exists()


class TestSynthesizeEdge:
    def test_import_error_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "edge_tts", raising=False)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.EDGETTS))
        monkeypatch.setattr(tts_obj, "_synthesize_system", lambda text, output_path: "system-out")
        assert tts_obj._synthesize_edge("hello") == "system-out"

    def test_success_default_voice(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_edge_tts(monkeypatch)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.EDGETTS, cache_dir=str(tmp_path)))
        out = tts_obj._synthesize_edge("hello")
        assert Path(out).read_bytes() == b"edge-data"
        assert state["text"] == "hello"
        assert state["voice"] == "en-US-AriaNeural"
        assert state["out"] == out

    def test_success_custom_voice(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        state = _install_fake_edge_tts(monkeypatch)
        out = tmp_path / "custom.mp3"
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.EDGETTS, voice="en-GB-SoniaNeural", cache_dir=str(tmp_path)))
        assert tts_obj._synthesize_edge("hello", output_path=str(out)) == str(out)
        assert state["voice"] == "en-GB-SoniaNeural"
        assert state["out"] == str(out)


class TestListVoices:
    def test_elevenlabs_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.ELEVENLABS))
        monkeypatch.setattr(tts_obj, "_list_elevenlabs_voices", lambda: [{"id": "x"}])
        assert tts_obj.list_voices() == [{"id": "x"}]

    def test_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "nt")
        tts_obj = TextToSpeech(TTSConfig())
        assert tts_obj.list_voices() == [{"id": "windows-sapi", "name": "Windows SAPI (default)"}]

    @pytest.mark.skipif(os.name == "nt", reason="macOS say branch requires a POSIX platform")
    def test_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "name", "posix")
        tts_obj = TextToSpeech(TTSConfig())
        assert tts_obj.list_voices() == [{"id": "macos-say", "name": "macOS say (default)"}]


class TestListElevenlabsVoices:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_elevenlabs(monkeypatch)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.ELEVENLABS))
        voices = tts_obj._list_elevenlabs_voices()
        assert voices == [{"id": "v1", "name": "Voice One"}, {"id": "v2", "name": "Voice Two"}]

    def test_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "elevenlabs", raising=False)
        tts_obj = TextToSpeech(TTSConfig(provider=TTSProvider.ELEVENLABS))
        assert tts_obj._list_elevenlabs_voices() == []

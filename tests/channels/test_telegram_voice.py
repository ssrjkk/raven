from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from raven.channels.telegram import voice as vmod
from raven.channels.telegram.voice import (
    _get_openai_key,
    _local_transcribe,
    download_voice,
    transcribe_voice,
)


class _FakeResp:
    def __init__(self, status_code: int = 200, json_data: Any = None, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.text = text

    def json(self) -> Any:
        return self._json


class _FakeClient:
    def __init__(self, resp: _FakeResp | None = None, exc: Exception | None = None) -> None:
        self._resp = resp or _FakeResp()
        self._exc = exc

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def post(self, *args: object, **kwargs: object) -> _FakeResp:
        if self._exc:
            raise self._exc
        return self._resp

    async def get(self, *args: object, **kwargs: object) -> _FakeResp:
        if self._exc:
            raise self._exc
        return self._resp


def _install_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client)


# ---------------------------------------------------------------------------
# transcribe_voice
# ---------------------------------------------------------------------------


async def test_transcribe_voice_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    f = tmp_path / "v.oga"
    f.write_bytes(b"oggdata")
    monkeypatch.setattr(vmod, "_get_openai_key", lambda: "sk-key")
    _install_client(monkeypatch, _FakeClient(resp=_FakeResp(200, {"text": "hello there"})))
    assert await transcribe_voice(str(f)) == "hello there"


async def test_transcribe_voice_api_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    f = tmp_path / "v.oga"
    f.write_bytes(b"oggdata")
    monkeypatch.setattr(vmod, "_get_openai_key", lambda: "sk-key")
    _install_client(monkeypatch, _FakeClient(resp=_FakeResp(401, text="unauthorized")))
    assert await transcribe_voice(str(f)) == ""


async def test_transcribe_voice_exception_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    f = tmp_path / "v.oga"
    f.write_bytes(b"oggdata")
    monkeypatch.setattr(vmod, "_get_openai_key", lambda: "sk-key")
    _install_client(monkeypatch, _FakeClient(exc=RuntimeError("boom")))
    assert await transcribe_voice(str(f)) == ""


async def test_transcribe_voice_no_key_uses_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    f = tmp_path / "v.oga"
    f.write_bytes(b"oggdata")
    monkeypatch.setattr(vmod, "_get_openai_key", lambda: "")
    # speech_recognition is not installed in the test env -> ImportError branch
    assert await transcribe_voice(str(f)) == "(speech_recognition not installed)"


async def test_transcribe_voice_httpx_missing_falls_back_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    f = tmp_path / "v.oga"
    f.write_bytes(b"oggdata")
    # a None entry in sys.modules makes `import httpx` raise ImportError
    monkeypatch.setitem(sys.modules, "httpx", None)
    assert await transcribe_voice(str(f)) == "(speech_recognition not installed)"


# ---------------------------------------------------------------------------
# download_voice
# ---------------------------------------------------------------------------


async def test_download_voice_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, _FakeClient(resp=_FakeResp(200, content=b"bytes!")))
    path = await download_voice("file/id.oga", "token")
    assert path is not None
    p = Path(path)
    try:
        assert p.read_bytes() == b"bytes!"
    finally:
        p.unlink()


async def test_download_voice_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, _FakeClient(resp=_FakeResp(404)))
    assert await download_voice("nope", "token") is None


async def test_download_voice_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch, _FakeClient(exc=RuntimeError("down")))
    assert await download_voice("nope", "token") is None


# ---------------------------------------------------------------------------
# _get_openai_key
# ---------------------------------------------------------------------------


def test_get_openai_key_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(openai_api_key=SimpleNamespace(get_secret_value=lambda: "secret"))
    monkeypatch.setattr("raven.core.config.settings", settings)
    assert _get_openai_key() == "secret"


def test_get_openai_key_settings_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(openai_api_key=SimpleNamespace(get_secret_value=lambda: ""))
    monkeypatch.setattr("raven.core.config.settings", settings)
    assert _get_openai_key() == ""


def test_get_openai_key_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> str:
        raise RuntimeError("no settings")

    settings = SimpleNamespace(openai_api_key=SimpleNamespace(get_secret_value=_boom))
    monkeypatch.setattr("raven.core.config.settings", settings)
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert _get_openai_key() == "env-key"


# ---------------------------------------------------------------------------
# _local_transcribe
# ---------------------------------------------------------------------------


def test_local_transcribe_import_error() -> None:
    # speech_recognition absent -> ImportError branch
    assert _local_transcribe("whatever.oga") == "(speech_recognition not installed)"


def test_local_transcribe_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Recognizer:
        def record(self, source: object) -> object:
            return source

        def recognize_google(self, audio: object) -> str:
            return "recognized text"

    class _AudioFile:
        def __init__(self, path: str) -> None:
            self.path = path

        def __enter__(self) -> str:
            return "src"

        def __exit__(self, *args: object) -> None:
            return None

    fake = SimpleNamespace(Recognizer=_Recognizer, AudioFile=_AudioFile)
    monkeypatch.setitem(sys.modules, "speech_recognition", fake)
    assert _local_transcribe("a.oga") == "recognized text"


def test_local_transcribe_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Recognizer:
        def record(self, source: object) -> object:
            return source

        def recognize_google(self, audio: object) -> str:
            raise ValueError("api down")

    class _AudioFile:
        def __init__(self, path: str) -> None:
            self.path = path

        def __enter__(self) -> str:
            return "src"

        def __exit__(self, *args: object) -> None:
            return None

    fake = SimpleNamespace(Recognizer=_Recognizer, AudioFile=_AudioFile)
    monkeypatch.setitem(sys.modules, "speech_recognition", fake)
    assert _local_transcribe("a.oga") == "(transcription failed: api down)"

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from loguru import logger


async def transcribe_voice(file_path: str) -> str:
    try:
        import httpx

        api_key = _get_openai_key()
        if not api_key:
            return _local_transcribe(file_path)

        with Path(file_path).open("rb") as f:
            async with httpx.AsyncClient(timeout=60) as c:
                resp = await c.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (Path(file_path).name, f, "audio/ogg")},
                    data={"model": "whisper-1"},
                )
                if resp.status_code == 200:
                    return resp.json().get("text", "")  # type: ignore[no-any-return]
                else:
                    logger.warning("Whisper API error: {} {}", resp.status_code, resp.text)
                    return ""
    except ImportError:
        return _local_transcribe(file_path)
    except Exception as e:
        logger.error("Voice transcription failed: {}", e)
        return ""


async def download_voice(file_id: str, bot_token: str) -> str | None:
    try:
        import httpx

        url = f"https://api.telegram.org/file/bot{bot_token}/{file_id}"
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.get(url)
            if resp.status_code == 200:
                fd, tmp_path = tempfile.mkstemp(suffix=".oga")
                os.close(fd)
                tmp = Path(tmp_path)
                tmp.write_bytes(resp.content)
                return str(tmp)
    except Exception as e:
        logger.error("Voice download failed: {}", e)
    return None


def _get_openai_key() -> str:
    try:
        from raven.core.config import settings

        return settings.openai_api_key or ""
    except Exception:
        import os

        return os.environ.get("OPENAI_API_KEY", "")


def _local_transcribe(file_path: str) -> str:
    try:
        import speech_recognition as sr

        r = sr.Recognizer()
        with sr.AudioFile(file_path) as source:
            audio = r.record(source)
        return r.recognize_google(audio)  # type: ignore[no-any-return]
    except ImportError:
        return "(speech_recognition not installed)"
    except Exception as e:
        return f"(transcription failed: {e})"

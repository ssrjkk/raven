from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

from loguru import logger

from raven.core.security.ssrf import safe_fetch_async, validate_url

PLUGIN_NAME = "ocr"
PLUGIN_DESCRIPTION = "Extract text from images using OCR (Tesseract)"

_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_+]+$")


def _allowed_roots() -> tuple[str, ...]:
    workspace = os.environ.get("RAVEN_WORKSPACE")
    roots = [tempfile.gettempdir()]
    if workspace:
        roots.append(str(Path(workspace).expanduser().resolve()))
    return tuple(roots)


ALLOWED_ROOTS = _allowed_roots()


def _check_image_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    for root in ALLOWED_ROOTS:
        r = Path(root).resolve()
        if r in p.parents or p == r:
            return p
    msg = f"Access denied: {path} (allowed: workspace, tmp)"
    raise PermissionError(msg)


def _check_language(language: str) -> str | None:
    if not language or not _LANGUAGE_RE.fullmatch(language):
        return None
    return language


async def ocr_image(image_path: str, language: str = "eng+rus") -> str:
    """Read the text out of one image file with Tesseract and return up to 4000 characters.

    image_path: Image readable by Tesseract, inside RAVEN_WORKSPACE or the system temp directory; anywhere else is
        refused.
    language: Tesseract language pack names joined with '+', e.g. 'eng' or 'eng+rus'. Anything outside letters,
        digits, '_' and '+' is refused.
    """
    try:
        p = _check_image_path(image_path)
        lang = _check_language(language)
        if lang is None:
            return f"Invalid OCR language: {language}"
        proc = await asyncio.create_subprocess_exec(
            "tesseract",
            str(p),
            "stdout",
            "-l",
            lang,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except PermissionError as e:
        logger.debug("[ocr] access denied: {}", e)
        return f"Error: {e}"
    except FileNotFoundError:
        return (
            "Tesseract not installed. Install: sudo apt install tesseract-ocr (Linux) or brew install tesseract (macOS)"
        )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    except TimeoutError:
        proc.kill()
        return "OCR timed out after 30s"
    text = stdout.decode("utf-8", errors="replace").strip()
    if stderr:
        err = stderr.decode("utf-8", errors="replace").strip()
        if err:
            logger.debug("Tesseract stderr: {}", err)
    if not text:
        return "No text detected in image"
    return text[:4000]


async def ocr_url(url: str, language: str = "eng+rus") -> str:
    """Download an image and run Tesseract over it, returning the recognised text up to 4000 characters.

    url: Image address. Loopback, private and link-local targets are refused before the request and again on every
        redirect.
    language: Tesseract language pack names joined with '+', e.g. 'eng' or 'eng+rus'.
    """
    if validate_url(url):
        return "Invalid or blocked URL (SSRF guard)"
    tmp = None
    try:
        resp = await safe_fetch_async(url, timeout=30.0)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
        return await ocr_image(tmp_path, language)
    except Exception as e:
        logger.debug("[ocr] URL error: {}", e)
        return f"OCR URL error: {e}"
    finally:
        if tmp and Path(tmp_path).exists():
            Path(tmp_path).unlink()

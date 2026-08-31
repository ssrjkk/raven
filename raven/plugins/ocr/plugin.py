from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

import httpx
from loguru import logger

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
    """Extract text from an image file using Tesseract OCR. Args: image_path (str): Path to image file, language (str): OCR language(s) like 'eng' or 'eng+rus'"""
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
    """Download image from URL and extract text via OCR. Args: url (str): Image URL, language (str): OCR language(s)"""
    from raven.core.security.ssrf import validate_url

    if validate_url(url):
        return "Invalid or blocked URL (SSRF guard)"
    tmp = None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
        return await ocr_image(tmp_path, language)
    except Exception as e:
        return f"OCR URL error: {e}"
    finally:
        if tmp and Path(tmp_path).exists():
            Path(tmp_path).unlink()

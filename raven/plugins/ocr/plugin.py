from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import httpx
from loguru import logger

PLUGIN_NAME = "ocr"
PLUGIN_DESCRIPTION = "Extract text from images using OCR (Tesseract)"


async def ocr_image(image_path: str, language: str = "eng+rus") -> str:
    """Extract text from an image file using Tesseract OCR. Args: image_path (str): Path to image file, language (str): OCR language(s) like 'eng' or 'eng+rus'"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tesseract",
            image_path,
            "stdout",
            "-l",
            language,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
    except FileNotFoundError:
        return (
            "Tesseract not installed. Install: sudo apt install tesseract-ocr (Linux) or brew install tesseract (macOS)"
        )
    except Exception as e:
        return f"OCR error: {e}"


async def ocr_url(url: str, language: str = "eng+rus") -> str:
    """Download image from URL and extract text via OCR. Args: url (str): Image URL, language (str): OCR language(s)"""
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

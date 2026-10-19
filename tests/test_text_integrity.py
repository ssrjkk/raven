"""No committed file may carry text that a botched codec produced, or a byte-order mark.

Both defects are what happens when a tool writes UTF-8 bytes through the host code page.
`web/src/components/DiffViewer.tsx` shipped its empty-diff glyph as eight characters
(U+0420 U+0406 U+0432 U+0402 U+040E U+0432 U+0402 U+045B) where one U+21C4 belonged: UTF-8
read as cp1251, written back as UTF-8, twice over. A byte-order mark is the same mistake one
layer down -- it survives import, but any tool that reads the file as plain UTF-8 and then
parses the string sees U+FEFF as a stray character and fails with an opaque SyntaxError.
Four test files had been carrying one since they were added.

Fixtures here are built from code points, never typed, so this file cannot itself be
corrupted by the codec it detects -- the last test proves that.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Code and asset directories: here any recoverable non-ASCII run is a defect, not prose.
SOURCE_DIRS = ("raven", "ravencode", "aios", "scripts", "web/src", "web/public",
               "extension", "site", "packaging", "deploy", "policy")
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".json",
                 ".svg", ".yml", ".yaml", ".toml"}
TEXT_SUFFIXES = CODE_SUFFIXES | {".md", ".txt", ".rst", ".sh", ".ps1", ".cfg", ".ini", ".env"}
SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__", ".venv", "venv", "Python",
             ".benchmarks", "allure-results", "test-results", "coverage", "playwright-report",
             ".next", ".cache", ".git"}
BOM = b"\xef\xbb\xbf"
NON_ASCII_RUN = re.compile(r"[^\x00-\x7f]+")


def _walk(directories: tuple[str, ...], suffixes: set[str]) -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for directory in directories:
        base = ROOT / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if SKIP_DIRS & set(path.relative_to(ROOT).parts):
                continue
            found.append(path)
    return sorted(found)


def code_files() -> list[pathlib.Path]:
    return _walk(SOURCE_DIRS, CODE_SUFFIXES)


def text_files() -> list[pathlib.Path]:
    found = _walk((*SOURCE_DIRS, "tests", "docs"), TEXT_SUFFIXES)
    found += [p for p in ROOT.glob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES]
    return sorted(found)


def double_encoded_runs(text: str) -> list[tuple[str, str]]:
    """Contiguous non-ASCII runs that turn into valid text when re-read through a code page."""
    offenders: list[tuple[str, str]] = []
    for run in NON_ASCII_RUN.findall(text):
        for codec in ("cp1251", "cp1252"):
            try:
                recovered = run.encode(codec).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            if recovered != run:
                offenders.append((run, recovered))
                break
    return offenders


def test_no_text_file_starts_with_a_byte_order_mark() -> None:
    files = text_files()
    assert len(files) > 500, f"walker found only {len(files)} files"
    offenders = [str(p.relative_to(ROOT)) for p in files if p.read_bytes().startswith(BOM)]
    assert offenders == []


def test_no_code_file_carries_double_encoded_text() -> None:
    files = code_files()
    assert len(files) > 300, f"walker found only {len(files)} files"
    offenders: list[str] = []
    for path in files:
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            offenders.append(f"{path.relative_to(ROOT)}: not valid UTF-8")
            continue
        for run, recovered in double_encoded_runs(text):
            offenders.append(f"{path.relative_to(ROOT)}: {run!r} was meant to be {recovered!r}")
    assert offenders == []


def test_the_guard_detects_the_pattern_it_forbids() -> None:
    corrupted = "".join(chr(c) for c in (0x0420, 0x0406, 0x0432, 0x0402, 0x040E, 0x0432, 0x0402, 0x045B))
    one_layer = "".join(chr(c) for c in (0x0432, 0x2021, 0x201E))
    assert double_encoded_runs(corrupted) == [(corrupted, one_layer)]
    assert double_encoded_runs(chr(0x21C4)) == []  # the glyph it was supposed to be


def test_the_guard_leaves_legitimate_non_ascii_alone() -> None:
    russian = "".join(chr(c) for c in (0x041F, 0x0440, 0x0438, 0x0432, 0x0435, 0x0442))
    cjk = "".join(chr(c) for c in (0x5185, 0x5BB9))
    dash, quote, arrow = chr(0x2014), chr(0x00AB), chr(0x21C4)
    for text in (russian, f"{russian}, {cjk} {dash} {quote}{russian}{chr(0x00BB)}", "plain ascii"):
        assert double_encoded_runs(text) == [], text


def test_this_file_holds_no_non_ascii_bytes() -> None:
    raw = pathlib.Path(__file__).read_bytes()
    bad = [i for i, byte in enumerate(raw) if byte > 127]
    assert bad == [], f"first stray byte at offset {bad[0]}"

from __future__ import annotations

import struct
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from raven.tools.reverse_engineering.binary_analyzer import (
    _calculate_entropy,
    _count_strings,
    _find_pe_text_section,
    _find_text_section_offset,
    _format_size,
    _parse_elf_raw,
    _try_pefile,
    _try_pyelftools,
    analyze_binary,
    extract_strings,
    get_file_type,
)


def _elf64(e_type: int = 3, e_machine: int = 62, endian: str = "little") -> bytes:
    b = bytearray(80)
    b[0:4] = b"\x7fELF"
    b[4] = 2  # 64-bit
    b[5] = 1 if endian == "little" else 2
    b[6] = 1
    fmt = "<" if endian == "little" else ">"
    struct.pack_into(fmt + "H", b, 16, e_type)
    struct.pack_into(fmt + "H", b, 18, e_machine)
    struct.pack_into(fmt + "H", b, 54, 2)  # e_phnum
    struct.pack_into(fmt + "H", b, 60, 3)  # e_shnum
    return bytes(b)


def _elf32(e_type: int = 1, e_machine: int = 3, endian: str = "big") -> bytes:
    b = bytearray(60)
    b[0:4] = b"\x7fELF"
    b[4] = 1  # 32-bit
    b[5] = 2 if endian == "big" else 1
    b[6] = 1
    fmt = ">" if endian == "big" else "<"
    struct.pack_into(fmt + "H", b, 16, e_type)
    struct.pack_into(fmt + "H", b, 18, e_machine)
    struct.pack_into(fmt + "H", b, 44, 1)  # e_phnum
    struct.pack_into(fmt + "H", b, 48, 1)  # e_shnum
    return bytes(b)


def _pe(machine: int = 0x8664, characteristics: int = 0x0002, num_sections: int = 0) -> bytes:
    b = bytearray(0x200)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80 : 0x84] = b"PE\x00\x00"
    struct.pack_into("<H", b, 0x84, machine)
    struct.pack_into("<H", b, 0x86, num_sections)
    struct.pack_into("<H", b, 0x92, characteristics)
    return bytes(b)


def _elf_with_section(
    sh_type: int = 1, sh_offset: int = 0x1000, sh_size: int = 8, bits: int = 64
) -> bytes:
    b = bytearray(512)
    b[0:4] = b"\x7fELF"
    b[4] = 2 if bits == 64 else 1
    b[5] = 1
    fmt = "<"
    shent = 64 if bits == 64 else 40
    struct.pack_into(fmt + "Q" if bits == 64 else fmt + "I", b, 40, 256)
    struct.pack_into(fmt + "H", b, 60, 1)  # e_shnum = 1
    struct.pack_into(fmt + "I", b, 256, 0)  # sh_name
    struct.pack_into(fmt + "I", b, 260, sh_type)
    if bits == 64:
        struct.pack_into(fmt + "Q", b, 256 + 24, sh_offset)
        struct.pack_into(fmt + "Q", b, 256 + 32, sh_size)
    else:
        struct.pack_into(fmt + "I", b, 256 + 16, sh_offset)
        struct.pack_into(fmt + "I", b, 256 + 20, sh_size)
    return bytes(b)


def _pe_with_text() -> bytes:
    b = bytearray(0x200)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80 : 0x84] = b"PE\x00\x00"
    struct.pack_into("<H", b, 0x86, 1)  # num_sections
    sh = 0x80 + 248
    b[sh : sh + 8] = b".text\x00\x00\x00"
    struct.pack_into("<I", b, sh + 20, 0x2000)
    return bytes(b)


def _write(tmp_path: Path, name: str, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


class TestGetFileType:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = get_file_type(str(tmp_path / "nope.bin"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_directory(self, tmp_path: Path) -> None:
        result = get_file_type(str(tmp_path))
        assert "error" in result
        assert "Not a file" in result["error"]

    def test_empty_file_unknown(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "empty.bin", b"")
        info = get_file_type(p)
        assert info["type"] == "Unknown"
        assert info["size"] == 0
        assert info["size_human"] == "0.0 B"

    def test_elf64_le(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "elf64", _elf64())
        info = get_file_type(p)
        assert info["type"] == "ELF"
        assert info["bits"] == 64
        assert info["endian"] == "little"
        assert info["file_type"] == "DYN"
        assert info["architecture"] == "x86-64"

    def test_elf64_be(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "elf64be", _elf64(endian="big"))
        info = get_file_type(p)
        assert info["endian"] == "big"
        assert info["architecture"] == "x86-64"

    def test_elf32(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "elf32", _elf32())
        info = get_file_type(p)
        assert info["bits"] == 32
        assert info["endian"] == "big"
        assert info["file_type"] == "REL"
        assert info["architecture"] == "x86"

    def test_pe_dll(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "a.dll", _pe(characteristics=0x2000))
        info = get_file_type(p)
        assert info["type"] == "PE"
        assert info["architecture"] == "x86-64 (AMD64)"
        assert info["subsystem"] == "DLL"

    def test_pe_exe(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "a.exe", _pe(machine=0x14C))
        info = get_file_type(p)
        assert info["subsystem"] == "EXE"
        assert info["architecture"] == "x86 (I386)"

    def test_pe_no_pe_signature(self, tmp_path: Path) -> None:
        b = bytearray(0x100)
        b[0:2] = b"MZ"
        p = _write(tmp_path, "odd.exe", bytes(b))
        info = get_file_type(p)
        assert info["type"] == "PE"
        assert "architecture" not in info

    def test_macho_32_be(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m32", b"\xfe\xed\xfa\xce" + b"\x00" * 12)
        info = get_file_type(p)
        assert info["type"] == "Mach-O"
        assert info["architecture"] == "32-bit big-endian"

    def test_macho_32_le(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m32l", b"\xce\xfa\xed\xfe" + b"\x00" * 12)
        info = get_file_type(p)
        assert info["type"] == "Mach-O"

    def test_macho_64(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m64", b"\xfe\xed\xfa\xcf" + b"\x00" * 12)
        info = get_file_type(p)
        assert info["type"] == "Mach-O"
        assert info["architecture"] == "64-bit"
        assert "endian" not in info

    def test_macho_64_le(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m64l", b"\xcf\xfa\xed\xfe" + b"\x00" * 12)
        info = get_file_type(p)
        assert info["architecture"] == "64-bit"
        assert info["endian"] == "little"

    def test_fat_binary(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "fat", b"\xca\xfe\xba\xbe" + b"\x00" * 12)
        info = get_file_type(p)
        assert info["type"] == "Universal Mach-O (Fat Binary)"

    def test_unknown_with_notes(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "rand.bin", b"\x00\x01\x02\x03" * 8)
        info = get_file_type(p)
        assert info["type"] == "Unknown"
        assert "notes" in info


class TestFormatSize:
    def test_b(self) -> None:
        assert _format_size(0) == "0.0 B"

    def test_kb(self) -> None:
        assert _format_size(1024) == "1.0 KB"

    def test_mb(self) -> None:
        assert _format_size(1024 * 1024) == "1.0 MB"

    def test_gb(self) -> None:
        assert _format_size(1024**3) == "1.0 GB"

    def test_tb(self) -> None:
        assert _format_size(1024**4) == "1.0 TB"


class TestTryPyelftools:
    def test_returns_none_when_not_installed(self, tmp_path: Path) -> None:
        assert _try_pyelftools(str(tmp_path / "x")) is None


class TestTryPefile:
    def test_returns_none_when_import_fails(self) -> None:
        with patch.dict(sys.modules, {"pefile": None}):
            assert _try_pefile("x.exe") is None

    def test_returns_error_on_parse_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = types.ModuleType("pefile")

        class PE:
            def __init__(self, path: str) -> None:
                raise ValueError("boom")

        stub.PE = PE  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pefile", stub)
        result = _try_pefile("x.exe")
        assert result is not None
        assert "error" in result


class TestParseElfRaw:
    def test_elf64(self) -> None:
        raw = _elf64()
        info = {"bits": 64, "endian": "little"}
        result = _parse_elf_raw(raw, info)
        assert result["segment_count"] == 2
        assert result["section_count"] == 3

    def test_elf32_be(self) -> None:
        raw = _elf32()
        info = {"bits": 32, "endian": "big"}
        result = _parse_elf_raw(raw, info)
        assert result["segment_count"] == 1
        assert result["section_count"] == 1


class TestFindTextSectionOffset:
    def test_elf64_finds_text(self) -> None:
        raw = _elf_with_section(sh_type=1, sh_offset=0x1000, sh_size=8, bits=64)
        assert _find_text_section_offset(raw, 256, 1, "<", 64) == 0x1000

    def test_parse_elf64_reports_text(self) -> None:
        raw = _elf_with_section(sh_type=1, sh_offset=0x1000, sh_size=8, bits=64)
        info = {"bits": 64, "endian": "little"}
        result = _parse_elf_raw(raw, info)
        assert result[".text_offset"] == "0x1000"
        assert result["segment_count"] == 0

    def test_elf32_finds_text(self) -> None:
        raw = _elf_with_section(sh_type=1, sh_offset=0x2000, sh_size=4, bits=32)
        assert _find_text_section_offset(raw, 256, 1, "<", 32) == 0x2000

    def test_no_text_section(self) -> None:
        raw = _elf_with_section(sh_type=8, sh_offset=0x1000, sh_size=8, bits=64)
        assert _find_text_section_offset(raw, 256, 1, "<", 64) is None

    def test_empty_size(self) -> None:
        raw = _elf_with_section(sh_type=1, sh_offset=0x1000, sh_size=0, bits=64)
        assert _find_text_section_offset(raw, 256, 1, "<", 64) is None

    def test_offset_out_of_bounds(self) -> None:
        raw = _elf_with_section(sh_type=1, sh_offset=0x1000, sh_size=8, bits=64)
        assert _find_text_section_offset(raw, 5000, 1, "<", 64) is None


class TestFindPeTextSection:
    def test_finds_text(self) -> None:
        raw = _pe_with_text()
        assert _find_pe_text_section(raw, 0x80) == 0x2000

    def test_no_text(self) -> None:
        raw = _pe()
        assert _find_pe_text_section(raw, 0x80) is None

    def test_truncated_section_table(self) -> None:
        raw = _pe_with_text()
        assert _find_pe_text_section(raw, 0x80) == 0x2000
        assert _find_pe_text_section(raw[:200], 0x80) is None

    def test_exception_bad_pe_offset(self) -> None:
        raw = _pe()
        assert _find_pe_text_section(raw, len(raw) - 2) is None


class TestAnalyzeBinary:
    def test_missing_file(self) -> None:
        result = analyze_binary("C:/does/not/exist.bin")
        assert result.startswith("[error]")
        assert "not found" in result

    def test_unknown_file(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "x.bin", b"random data here")
        result = analyze_binary(p)
        assert "Format: Unknown" in result
        assert "Entropy:" in result
        assert "Strings found:" in result

    def test_elf_file(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "prog", _elf64())
        result = analyze_binary(p)
        assert "Format: ELF" in result
        assert "Architecture: x86-64" in result
        assert "Segments: 2" in result
        assert "Sections: 3" in result

    def test_pe_file(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "prog.exe", _pe())
        result = analyze_binary(p)
        assert "Format: PE" in result
        assert "Entropy:" in result


class TestExtractStrings:
    def test_ascii_and_unicode(self, tmp_path: Path) -> None:
        payload = b"hello world" + "hello".encode("utf-16-le") + b"\x00\x00"
        p = _write(tmp_path, "s.bin", payload)
        result = extract_strings(p)
        assert "hello world" in result
        assert "Unicode strings: 1" in result
        assert "ASCII strings:" in result

    def test_missing_file(self) -> None:
        assert "not found" in extract_strings("C:/nope.bin")

    def test_classify(self, tmp_path: Path) -> None:
        url = b"https://example.com/callback"
        path = b"/usr/local/bin"
        crypto = b"ABCDEF0123456789ABCDEF0123456789"
        ip = b"10.0.0.1"
        registry = b"HKLM\\Software\\Raven"
        func = b"myFunction"
        sep = b"\x00"
        data = sep.join([url, path, crypto, ip, registry, func]) + sep
        p = _write(tmp_path, "c.bin", data)
        result = extract_strings(p, min_length=3, classify=True)
        assert "[urls]" in result and "https://example.com" in result
        assert "[paths]" in result and "/usr/local/bin" in result
        assert "[crypto]" in result
        assert "[ip]" in result and "10.0.0.1" in result
        assert "[registry]" in result
        assert "[function_names]" in result and "myFunction" in result

    def test_truncated_list(self, tmp_path: Path) -> None:
        payload = b"".join(f"string_{i:03d} padding".encode() for i in range(50))
        p = _write(tmp_path, "many.bin", payload)
        result = extract_strings(p, min_length=3)
        assert "... and " not in result

    def test_truncated_list_over_200(self, tmp_path: Path) -> None:
        payload = b"\x00".join(f"unique_string_{i:05d}_abc".encode() for i in range(300))
        p = _write(tmp_path, "many2.bin", payload)
        result = extract_strings(p, min_length=5)
        assert "... and " in result

    def test_classify_truncated_50(self, tmp_path: Path) -> None:
        payload = b"\x00".join(f"plain-token-{i:04d}".encode() for i in range(60))
        p = _write(tmp_path, "many3.bin", payload)
        result = extract_strings(p, min_length=5, classify=True)
        assert "... and 10 more" in result
        assert "[other] (60):" in result


class TestEntropyAndStrings:
    def test_entropy_empty(self) -> None:
        assert _calculate_entropy(b"") == 0.0

    def test_entropy_uniform(self) -> None:
        assert _calculate_entropy(b"\x00" * 100) == 0.0

    def test_entropy_max(self) -> None:
        assert _calculate_entropy(bytes(range(256))) == 8.0

    def test_count_strings(self) -> None:
        data = b"AAAA\x00BBBB\x00CCCC"
        assert _count_strings(data) == 3

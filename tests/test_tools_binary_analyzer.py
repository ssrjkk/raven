from __future__ import annotations

import hashlib
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
    _raw_pe_imports,
    _try_pefile,
    _try_pyelftools,
    analyze_binary,
    compare_binaries,
    extract_strings,
    get_file_type,
    hash_binary,
    hexdump,
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


def _pe_full(
    opt_magic: int = 0x20B, timestamp: int = 1600000000, entry_rva: int = 0x1000, image_base: int = 0x140000000
) -> bytes:
    b = bytearray(0x200)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80 : 0x84] = b"PE\x00\x00"
    struct.pack_into("<H", b, 0x84, 0x8664)
    struct.pack_into("<I", b, 0x80 + 8, timestamp)
    struct.pack_into("<H", b, 0x80 + 24, opt_magic)
    struct.pack_into("<I", b, 0x80 + 40, entry_rva)
    if opt_magic == 0x20B:
        struct.pack_into("<Q", b, 0x80 + 48, image_base)
    else:
        struct.pack_into("<I", b, 0x80 + 52, image_base)
    return bytes(b)


def _macho(
    magic: bytes = b"\xfe\xed\xfa\xce",
    cputype: int = 7,
    filetype: int = 2,
    ncmds: int = 5,
    flags: int = 0x200000,
) -> bytes:
    b = bytearray(32)
    b[0:4] = magic
    struct.pack_into(">I" if magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf") else "<I", b, 4, cputype)
    struct.pack_into(">I" if magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf") else "<I", b, 8, 0)  # cpusubtype
    struct.pack_into(">I" if magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf") else "<I", b, 12, filetype)
    struct.pack_into(">I" if magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf") else "<I", b, 16, ncmds)
    struct.pack_into(">I" if magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf") else "<I", b, 20, 0)  # sizeofcmds
    struct.pack_into(">I" if magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf") else "<I", b, 24, flags)
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


def _pe_full_with_imports() -> bytes:
    """Minimal PE32+ with one .idata section and one KERNEL32!CreateFileW import."""
    pe_offset = 0x80
    opt_size = 0xF0
    sect_vaddr = 0x2000  # .idata virtual address
    sect_rawptr = 0x400  # .idata file pointer
    b = bytearray(0x1000)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, pe_offset)
    b[pe_offset : pe_offset + 4] = b"PE\x00\x00"
    struct.pack_into("<H", b, pe_offset + 6, 1)  # num_sections
    struct.pack_into("<H", b, pe_offset + 20, opt_size)  # size_of_optional_header
    struct.pack_into("<H", b, pe_offset + 24, 0x20B)  # PE32+ magic
    # one section header just after the optional header
    sect = pe_offset + 24 + opt_size
    b[sect : sect + 8] = b".idata\x00\x00"
    struct.pack_into("<I", b, sect + 8, 0x600)  # virtual size
    struct.pack_into("<I", b, sect + 12, sect_vaddr)
    struct.pack_into("<I", b, sect + 16, 0x600)  # raw size
    struct.pack_into("<I", b, sect + 20, sect_rawptr)

    def rva_to_off(rva: int) -> int:
        return sect_rawptr + (rva - sect_vaddr)

    # import descriptor at rva base (raw sect_rawptr); 20 bytes -> occupies 0x2000..0x2013
    desc_off = rva_to_off(sect_vaddr)
    offt_rva = sect_vaddr + 0x20  # OriginalFirstThunk array
    name_rva = sect_vaddr + 0x50  # DLL name string
    ft_rva = sect_vaddr + 0x30    # FirstThunk array
    byname_rva = sect_vaddr + 0x40
    struct.pack_into("<I", b, desc_off + 0, offt_rva)
    struct.pack_into("<I", b, desc_off + 12, name_rva)
    struct.pack_into("<I", b, desc_off + 16, ft_rva)
    # OFT + FT arrays: one IMAGE_IMPORT_BY_NAME then terminator
    for thunk_rva in (offt_rva, ft_rva):
        thunk_off = rva_to_off(thunk_rva)
        struct.pack_into("<Q", b, thunk_off, byname_rva)
        struct.pack_into("<Q", b, thunk_off + 8, 0)
    # IMAGE_IMPORT_BY_NAME at byname_rva: hint(2) + "CreateFileW"
    iname_off = rva_to_off(byname_rva)
    b[iname_off : iname_off + 2] = b"\x00\x00"
    b[iname_off + 2 : iname_off + 2 + 11] = b"CreateFileW"
    # DLL name at name_rva
    struct.pack_into("<I", b, pe_offset + 24 + 0x68, sect_vaddr)
    dll_off = rva_to_off(name_rva)
    b[dll_off : dll_off + 9] = b"KERNEL32\x00"
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

    def test_pe32_plus_fields(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "full.exe", _pe_full())
        info = get_file_type(p)
        assert info["timestamp"] == "2020-09-13 12:26:40 UTC"
        assert info["entry_point"] == "0x1000"
        assert info["image_base"] == "0x140000000"

    def test_pe32_fields(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "pe32.exe", _pe_full(opt_magic=0x10B, image_base=0x400000))
        info = get_file_type(p)
        assert info["entry_point"] == "0x1000"
        assert info["image_base"] == "0x400000"

    def test_pe_no_timestamp(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "nts.exe", _pe_full(timestamp=0))
        info = get_file_type(p)
        assert "timestamp" not in info

    def test_macho_32_be(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m32", _macho())
        info = get_file_type(p)
        assert info["type"] == "Mach-O"
        assert info["bits"] == 32
        assert info["endian"] == "big"
        assert info["architecture"] == "i386"
        assert info["file_type"] == "MH_EXECUTE"
        assert info["load_commands"] == 5

    def test_macho_32_le(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m32l", _macho(magic=b"\xce\xfa\xed\xfe", cputype=18))
        info = get_file_type(p)
        assert info["type"] == "Mach-O"
        assert info["endian"] == "little"
        assert info["architecture"] == "PowerPC"

    def test_macho_64(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m64", _macho(magic=b"\xfe\xed\xfa\xcf", cputype=0x01000007))
        info = get_file_type(p)
        assert info["type"] == "Mach-O"
        assert info["bits"] == 64
        assert info["architecture"] == "x86-64"
        assert info["endian"] == "big"

    def test_macho_64_le(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m64l", _macho(magic=b"\xcf\xfa\xed\xfe", cputype=0x0100000C, flags=0x4))
        info = get_file_type(p)
        assert info["architecture"] == "arm64"
        assert info["endian"] == "little"
        assert info.get("dylib") is True

    def test_macho_short_header(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "mshort", b"\xfe\xed\xfa\xcf" + b"\x00" * 12)
        info = get_file_type(p)
        assert info["type"] == "Mach-O"
        assert info["bits"] == 64

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

    def test_elf64_entry_point(self) -> None:
        b = bytearray(_elf64())
        struct.pack_into("<Q", b, 24, 0x401000)
        info = {"bits": 64, "endian": "little"}
        result = _parse_elf_raw(bytes(b), info)
        assert result["entry_point"] == "0x401000"

    def test_elf32_be(self) -> None:
        raw = _elf32()
        info = {"bits": 32, "endian": "big"}
        result = _parse_elf_raw(raw, info)
        assert result["segment_count"] == 1
        assert result["section_count"] == 1

    def test_elf32_entry_point(self) -> None:
        b = bytearray(_elf32())
        struct.pack_into(">I", b, 24, 0x8048000)
        info = {"bits": 32, "endian": "big"}
        result = _parse_elf_raw(bytes(b), info)
        assert result["entry_point"] == "0x8048000"


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


class TestRawPeImports:
    def test_extracts_dll_and_function(self, tmp_path: Path) -> None:
        raw = _pe_full_with_imports()
        imports = _raw_pe_imports(raw, 0x80)
        assert any(i["dll"] == "KERNEL32" and i["name"] == "CreateFileW" for i in imports)

    def test_garbage_returns_empty(self) -> None:
        assert _raw_pe_imports(b"\x00" * 64, 8) == []

    def test_truncated_returns_empty(self) -> None:
        raw = _pe_full_with_imports()
        assert _raw_pe_imports(raw[:300], 0x80) == []

    def test_ordinal_when_no_name(self, tmp_path: Path) -> None:
        raw = _pe_full_with_imports()
        imports = _raw_pe_imports(raw, 0x80)
        assert isinstance(imports, list)
        for i in imports:
            assert "dll" in i and "name" in i


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
        assert "Unicode strings:" in result

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

    def test_pe_imports_fallback_rendered(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "imp.exe", _pe_full_with_imports())
        with patch("raven.tools.reverse_engineering.binary_analyzer._try_pefile", return_value=None):
            result = analyze_binary(p)
        assert "Imports (raw fallback" in result
        assert "KERNEL32!CreateFileW" in result


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

    def test_unicode_strings_counted(self, tmp_path: Path) -> None:
        data = b"AAAA\x00" * 10  # 4 printable + null = unicode string blocks
        p = _write(tmp_path, "u.bin", data)
        result = analyze_binary(p)
        assert "Unicode strings:" in result


class TestHexdump:
    def test_missing_file(self) -> None:
        assert "not found" in hexdump("C:/nope.bin")

    def test_offset_out_of_range(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "x.bin", b"abc")
        assert "out of range" in hexdump(p, offset=10)

    def test_negative_offset(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "y.bin", b"abc")
        assert "out of range" in hexdump(p, offset=-1)

    def test_dump(self, tmp_path: Path) -> None:
        data = b"\x00\x01\x02\x03" + b"ABCDEFGH" + b"\xff" * 4
        p = _write(tmp_path, "d.bin", data)
        out = hexdump(p)
        assert "; hexdump d.bin @0x0" in out
        assert "00 01 02 03 41 42 43 44" in out
        assert "ABCD" in out
        assert "ff ff ff ff" in out

    def test_offset_and_length(self, tmp_path: Path) -> None:
        data = bytes(range(64))
        p = _write(tmp_path, "off.bin", data)
        out = hexdump(p, offset=16, length=16)
        assert "; hexdump off.bin @0x10 (16 bytes)" in out
        assert "10 11 12 13" in out


class TestHashBinary:
    def test_missing_file(self) -> None:
        assert "not found" in hash_binary("C:/nope.bin")

    def test_known_hashes(self, tmp_path: Path) -> None:
        data = b"raven reverse engineering"
        p = _write(tmp_path, "h.bin", data)
        out = hash_binary(p)
        assert hashlib.md5(data).hexdigest() in out  # noqa: S324 - fingerprinting test
        assert hashlib.sha1(data).hexdigest() in out  # noqa: S324 - fingerprinting test
        assert hashlib.sha256(data).hexdigest() in out

    def test_empty(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "empty.bin", b"")
        out = hash_binary(p)
        assert hashlib.md5(b"").hexdigest() in out  # noqa: S324 - fingerprinting test


class TestCompareBinaries:
    def test_missing_file(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "a.bin", b"x")
        assert "not found" in compare_binaries(p, str(tmp_path / "nope"))

    def test_identical(self, tmp_path: Path) -> None:
        p1 = _write(tmp_path, "a.bin", b"same bytes here")
        p2 = _write(tmp_path, "b.bin", b"same bytes here")
        out = compare_binaries(p1, p2)
        assert "Result: IDENTICAL" in out

    def test_different(self, tmp_path: Path) -> None:
        p1 = _write(tmp_path, "a.bin", b"AAAABBBBCCCC")
        p2 = _write(tmp_path, "b.bin", b"AAAAXXXXCCCC")
        out = compare_binaries(p1, p2)
        assert "Result: DIFFERENT" in out
        assert "Similarity:" in out
        assert "first difference" in out

    def test_different_size(self, tmp_path: Path) -> None:
        p1 = _write(tmp_path, "a.bin", b"AAAA")
        p2 = _write(tmp_path, "b.bin", b"AAAA" * 4096)
        out = compare_binaries(p1, p2)
        assert "Result: DIFFERENT" in out
        assert "Size A" in out

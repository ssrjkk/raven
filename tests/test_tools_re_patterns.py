from __future__ import annotations

import struct
from pathlib import Path

import pytest

from raven.tools.reverse_engineering.patterns import (
    ANTI_DEBUG_PATTERNS,
    CRYPTO_CONSTANTS,
    PACKER_SIGNATURES,
    _extract_imports,
    _rva_to_raw,
    _scan_anti_debug,
    _scan_apis,
    _scan_crypto,
    _scan_packers,
    _scan_vulns,
    detect_patterns,
)


def _write(tmp_path: Path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _dump(lines: list[str]) -> str:
    return "\n".join(lines)


def _pe_raw(
    descriptors: list[tuple[int, int]],
    name_blobs: list[tuple[int, bytes]],
    opt_magic: int = 0x10B,
    import_dir_rva: int = 0x1000,
) -> bytes:
    pe_off = 0x80
    b = bytearray(0x700)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, pe_off)
    struct.pack_into("<H", b, pe_off + 6, 1)
    struct.pack_into("<H", b, pe_off + 24, opt_magic)
    if opt_magic == 0x10B:
        struct.pack_into("<I", b, pe_off + 104, import_dir_rva)
    elif opt_magic == 0x20B:
        struct.pack_into("<I", b, pe_off + 120, import_dir_rva)
    sect_off = pe_off + 248
    struct.pack_into("<I", b, sect_off + 8, 0x1000)
    struct.pack_into("<I", b, sect_off + 12, 0x1000)
    struct.pack_into("<I", b, sect_off + 16, 0x1000)
    struct.pack_into("<I", b, sect_off + 20, 0x400)
    off = 0x400
    for ilt, name_rva in descriptors:
        struct.pack_into("<I", b, off, ilt)
        struct.pack_into("<I", b, off + 12, name_rva)
        off += 20
    for foff, blob in name_blobs:
        b[foff : foff + len(blob)] = blob
    return bytes(b)


def _pe_imports(names: list[str], opt_magic: int = 0x10B, import_dir_rva: int = 0x1000) -> bytes:
    blobs = [
        (0x500 + sum(len(n.encode()) + 3 for n in names[:i]), b"\x00\x00" + n.encode() + b"\x00")
        for i, n in enumerate(names)
    ]
    descriptors = [(1, 0x1000 + (off - 0x400)) for off, _blob in blobs]
    return _pe_raw(descriptors, blobs, opt_magic=opt_magic, import_dir_rva=import_dir_rva)


def _elf_raw(names: list[str]) -> bytes:
    return b"\x7fELF\x00" + b"\x00".join(n.encode() for n in names)


def _everything_raw() -> bytes:
    b = bytearray(0x200)
    b[0:4] = b"\x7fELF"
    b[0x40 : 0x46] = b"ASPack"
    b[0x50 : 0x58] = b"\x63\x7c\x77\x7b\xf2\x6b\x6f\xc5"
    b[0x60 : 0x66] = b"\x64\xa1\x30\x00\x00\x00"
    b[0x80 : 0x86] = b"strcpy"
    b[0x90 : 0xB5] = b"\x00VirtualAllocEx\x00CryptEncrypt\x00WSASend\x00"
    return bytes(b)


def _section_raw(vsize: int = 0x1000, raw_size: int = 0x1000, num_sections: int = 1) -> bytes:
    pe_off = 0x80
    b = bytearray(0x300)
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, pe_off)
    struct.pack_into("<H", b, pe_off + 6, num_sections)
    sect_off = pe_off + 248
    struct.pack_into("<I", b, sect_off + 8, vsize)
    struct.pack_into("<I", b, sect_off + 12, 0x1000)
    struct.pack_into("<I", b, sect_off + 16, raw_size)
    struct.pack_into("<I", b, sect_off + 20, 0x400)
    return bytes(b)


_ANTI_DEBUG_RAW: dict[str, bytes] = {
    "ptrace": b"\xbe\x0f\x00\x00\x00\xbf\x02\x00\x00\x00",
    "IsDebuggerPresent": b"\x64\xa1\x30\x00\x00\x00",
    "NtGlobalFlag": b"\x64\xa1\x18\x00\x00\x00",
    "OutputDebugString": b"\xff\x15\x00",
    "TrapFlag": b"\x9c\x50\x81\x61\x00\x00\x00\x00\x00\x01\x00\x00",
    "TimingCheck": b"\x0f\x31",
}

_DANGEROUS: list[tuple[bytes, str]] = [
    (b"strcpy", "strcpy: buffer overflow risk"),
    (b"strcat", "strcat: buffer overflow risk"),
    (b"sprintf", "sprintf: format string overflow risk"),
    (b"gets", "gets: unbounded input risk"),
    (b"scanf", "scanf: unbounded input risk"),
    (b"system", "system: shell injection risk (if used with user input)"),
    (b"popen", "popen: shell injection risk"),
    (b"exec", "exec: code execution risk"),
    (b"alloca", "alloca: stack overflow risk"),
    (b"memcpy", "memcpy: buffer overflow if size miscalculated"),
    (b"wcscpy", "wcscpy: wide buffer overflow risk"),
]


class TestScanPackers:
    @pytest.mark.parametrize(
        ("offset", "sig", "desc"),
        [(off, sig, desc) for _name, entries, desc in PACKER_SIGNATURES for off, sig in entries],
    )
    def test_each_signature(self, offset: int, sig: bytes, desc: str) -> None:
        out = _scan_packers(b"\x00" * offset + sig + b"\xff")
        assert f"  [PACKER] {desc}" in _dump(out)

    def test_no_signatures(self) -> None:
        out = _scan_packers(b"\x00" * 64)
        assert "No known packer signatures found" in _dump(out)

    def test_short_raw(self) -> None:
        assert "No known packer signatures found" in _dump(_scan_packers(b""))

    def test_str_signature_encoded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.patterns.PACKER_SIGNATURES",
            [("T", [(0, "ABC")], "test packer")],
        )
        out = _scan_packers(b"ABC\xff")
        assert "[PACKER] test packer" in _dump(out)


class TestScanCrypto:
    @pytest.mark.parametrize("name,sig,desc", CRYPTO_CONSTANTS)
    def test_each_constant(self, name: str, sig: bytes, desc: str) -> None:
        out = _scan_crypto(sig + b"\xff")
        assert f"  [CRYPTO] {desc}" in _dump(out)

    def test_all_constants(self) -> None:
        raw = b"".join(sig for _n, sig, _d in CRYPTO_CONSTANTS)
        out = _scan_crypto(raw)
        for _n, _s, desc in CRYPTO_CONSTANTS:
            assert f"  [CRYPTO] {desc}" in _dump(out)

    def test_none(self) -> None:
        assert "No known crypto constants found" in _dump(_scan_crypto(b"\x00" * 32))


class TestScanAntiDebug:
    @pytest.mark.parametrize("name,pattern,desc", ANTI_DEBUG_PATTERNS)
    def test_each_pattern(self, name: str, pattern: str, desc: str) -> None:
        out = _scan_anti_debug(_ANTI_DEBUG_RAW[name] + b"\xff")
        assert f"  [ANTI-DEBUG] {desc}" in _dump(out)

    def test_none(self) -> None:
        assert "No anti-debug patterns found" in _dump(_scan_anti_debug(b"\x00" * 32))

    def test_invalid_regex_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.patterns.ANTI_DEBUG_PATTERNS",
            [("bad", "[", "invalid pattern")],
        )
        out = _scan_anti_debug(b"\x00" * 8)
        assert "No anti-debug patterns found" in _dump(out)


class TestScanVulns:
    @pytest.mark.parametrize(("token", "desc"), _DANGEROUS)
    def test_each_function(self, token: bytes, desc: str) -> None:
        out = _scan_vulns(b"xx" + token + b"yy")
        assert f"  [VULN] {desc}" in _dump(out)

    def test_all_functions(self) -> None:
        raw = b"\x00".join(token for token, _desc in _DANGEROUS)
        out = _scan_vulns(raw)
        for _token, desc in _DANGEROUS:
            assert f"  [VULN] {desc}" in _dump(out)

    def test_none(self) -> None:
        assert "No obvious vulnerability indicators" in _dump(_scan_vulns(b"\x00\x01\x02"))


class TestScanApis:
    def test_no_import_table(self) -> None:
        out = _scan_apis(b"random data here")
        assert "(no import table or import parsing disabled)" in _dump(out)

    def test_elf_findings(self) -> None:
        names = [
            "VirtualAllocEx",
            "NtQueryInformationProcess",
            "GetAsyncKeyState",
            "RegSetValueEx",
            "send",
            "recv",
            "connect",
            "WSASend",
            "WSARecv",
            "socket",
            "bind",
            "listen",
            "accept",
            "WSAStartup",
            "InternetOpen",
            "InternetConnect",
            "CryptEncrypt",
            "NtOpenProcess",
        ]
        out = _scan_apis(_elf_raw(names))
        assert "[process_injection] (1): VirtualAllocEx" in _dump(out)
        assert "[anti_debug_api] (1): NtQueryInformationProcess" in _dump(out)
        assert "[keylog_sniff] (1): GetAsyncKeyState" in _dump(out)
        assert "[persistence] (1): RegSetValueEx" in _dump(out)
        assert (
            "[network] (12): send, recv, connect, WSASend, WSARecv, socket, bind, listen, accept, WSAStartup"
            in _dump(out)
        )
        assert "[crypto] (1): CryptEncrypt" in _dump(out)
        assert "[injection_bypass] (1): NtOpenProcess" in _dump(out)
        assert "InternetOpen" not in _dump(out)

    def test_no_suspicious_apis(self) -> None:
        out = _scan_apis(_pe_imports(["KERNEL32.dll"]))
        assert "No suspicious APIs found" in _dump(out)

    def test_pe_imports(self) -> None:
        out = _scan_apis(_pe_imports(["VirtualAllocEx", "WSASend", "CryptEncrypt"]))
        assert "[process_injection] (1): VirtualAllocEx" in _dump(out)
        assert "[network] (1): WSASend" in _dump(out)
        assert "[crypto] (1): CryptEncrypt" in _dump(out)

    def test_scan_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(raw: bytes) -> set[str]:
            raise RuntimeError("import parse failed")

        monkeypatch.setattr("raven.tools.reverse_engineering.patterns._extract_imports", boom)
        out = _scan_apis(b"\x00\x01\x02")
        assert "API scan error: import parse failed" in _dump(out)


class TestExtractImports:
    def test_unrecognized_format(self) -> None:
        assert _extract_imports(b"random data here") == set()

    def test_elf_finds_api_names(self) -> None:
        raw = _elf_raw(["VirtualAllocEx", "ZZZZ", "send"])
        assert _extract_imports(raw) == {"VirtualAllocEx", "send"}

    def test_macho_magic_never_matches(self) -> None:
        raw = b"\xfe\xed\xfa\xce\x00VirtualAllocEx\x00"
        assert _extract_imports(raw) == set()

    def test_pe32_imports(self) -> None:
        raw = _pe_imports(["VirtualAllocEx", "CryptEncrypt"])
        assert _extract_imports(raw) == {"VirtualAllocEx", "CryptEncrypt"}

    def test_pe32plus_imports(self) -> None:
        raw = _pe_imports(["WSASend"], opt_magic=0x20B)
        assert _extract_imports(raw) == {"WSASend"}

    def test_unknown_opt_magic_skips_import_dir(self) -> None:
        raw = _pe_imports(["WSASend"], opt_magic=0x1234)
        assert _extract_imports(raw) == set()

    def test_zero_import_dir_rva(self) -> None:
        raw = _pe_imports(["WSASend"], import_dir_rva=0)
        assert _extract_imports(raw) == set()

    def test_import_dir_outside_sections(self) -> None:
        raw = _pe_imports(["WSASend"], import_dir_rva=0x9000)
        assert _extract_imports(raw) == set()

    def test_name_rva_maps_to_none(self) -> None:
        raw = _pe_raw([(1, 0x9000), (1, 0x1100)], [(0x500, b"\x00\x00WSASend\x00")])
        assert _extract_imports(raw) == {"WSASend"}

    def test_name_raw_near_eof_skipped(self) -> None:
        raw = _pe_raw([(1, 0x12FF)], [])
        assert _extract_imports(raw) == set()

    def test_empty_name_skipped(self) -> None:
        raw = _pe_raw([(1, 0x1100)], [(0x500, b"\x00\x00\x00")])
        assert _extract_imports(raw) == set()

    def test_descriptor_without_name_rva_skipped(self) -> None:
        raw = _pe_raw([(1, 0x1100), (5, 0)], [(0x500, b"\x00\x00WSASend\x00")])
        assert _extract_imports(raw) == {"WSASend"}

    def test_loop_exits_when_table_exhausted(self) -> None:
        b = bytearray(0x33C)
        b[0:2] = b"MZ"
        struct.pack_into("<I", b, 0x3C, 0x80)
        struct.pack_into("<H", b, 0x86, 1)
        struct.pack_into("<H", b, 0x98, 0x10B)
        struct.pack_into("<I", b, 0xE8, 0x1000)
        struct.pack_into("<I", b, 0x180, 0x200)
        struct.pack_into("<I", b, 0x184, 0x1000)
        struct.pack_into("<I", b, 0x188, 0x200)
        struct.pack_into("<I", b, 0x18C, 0x300)
        struct.pack_into("<I", b, 0x300, 1)
        struct.pack_into("<I", b, 0x30C, 0x1030)
        struct.pack_into("<I", b, 0x314, 5)
        struct.pack_into("<I", b, 0x328, 6)
        struct.pack_into("<H", b, 0x330, 0)
        b[0x332:0x339] = b"WSASend"
        b[0x339] = 0
        assert _extract_imports(bytes(b)) == {"WSASend"}

    def test_parse_error_logged(self) -> None:
        raw = bytearray(0x80)
        raw[0:2] = b"MZ"
        struct.pack_into("<I", raw, 0x3C, 0x7FFFFFF0)
        assert _extract_imports(bytes(raw)) == set()


class TestRvaToRaw:
    def test_rva_at_vaddr(self) -> None:
        assert _rva_to_raw(_section_raw(), 0x1000, 1, 0x178, 0x80) == 0x400

    def test_rva_inside_section(self) -> None:
        assert _rva_to_raw(_section_raw(), 0x1500, 1, 0x178, 0x80) == 0x900

    def test_rva_out_of_section(self) -> None:
        assert _rva_to_raw(_section_raw(), 0x3000, 1, 0x178, 0x80) is None

    def test_no_sections(self) -> None:
        assert _rva_to_raw(_section_raw(num_sections=0), 0x1000, 0, 0x178, 0x80) is None

    def test_rva_beyond_vsize_but_within_raw_size(self) -> None:
        raw = _section_raw(vsize=0x100, raw_size=0x200)
        assert _rva_to_raw(raw, 0x1100, 1, 0x178, 0x80) == 0x500

    def test_rva_beyond_raw_size_but_within_vsize(self) -> None:
        raw = _section_raw(vsize=0x300, raw_size=0x100)
        assert _rva_to_raw(raw, 0x1100, 1, 0x178, 0x80) == 0x500


class TestDetectPatterns:
    def test_file_not_found(self, tmp_path: Path) -> None:
        path = str(tmp_path / "missing.bin")
        assert detect_patterns(path) == f"[error] File not found: {path}"

    def test_default_all_scans(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "all.bin", _everything_raw())
        out = detect_patterns(p)
        assert "=== Pattern Detection: all.bin ===" in out
        assert "  File size: 512 bytes" in out
        assert "[PACKER]" in out
        assert "[CRYPTO]" in out
        assert "[ANTI-DEBUG]" in out
        assert "[VULN]" in out
        assert "[process_injection]" in out

    def test_single_pattern(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "p.bin", _everything_raw())
        out = detect_patterns(p, patterns="packers")
        assert "[PACKER]" in out
        assert "[CRYPTO]" not in out
        assert "[ANTI-DEBUG]" not in out
        assert "[VULN]" not in out
        assert "[process_injection]" not in out

    def test_multiple_patterns(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "m.bin", _everything_raw())
        out = detect_patterns(p, patterns="packers,crypto")
        assert "[PACKER]" in out
        assert "[CRYPTO]" in out
        assert "[ANTI-DEBUG]" not in out

    def test_case_insensitive_patterns(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "c.bin", _everything_raw())
        out = detect_patterns(p, patterns="PACKERS")
        assert "[PACKER]" in out
        assert "[CRYPTO]" not in out

    def test_unknown_pattern_runs_no_scans(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "u.bin", b"\x00\x01")
        out = detect_patterns(p, patterns="bogus")
        assert "Total findings: -1" in out

    def test_empty_pattern_string(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "e.bin", b"\x00\x01")
        assert "Total findings: -1" in detect_patterns(p, patterns="")

    def test_pattern_whitespace_not_stripped(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "w.bin", _everything_raw())
        out = detect_patterns(p, patterns="packers, crypto")
        assert "[PACKER]" in out
        assert "[CRYPTO]" not in out

    def test_single_scan_no_findings_count(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "n.bin", b"\x00" * 64)
        out = detect_patterns(p, patterns="packers")
        assert "No known packer signatures found" in out
        assert "Total findings: 1" in out

    def test_directory_raises_oserror(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            detect_patterns(str(tmp_path))

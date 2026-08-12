from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from raven.tools.reverse_engineering.disassembler import (
    _extract_code_bytes,
    _fallback_disassemble,
    _find_text_section,
    _guess_arch_from_binary,
    _resolve_symbol,
    disassemble_bytes,
    disassemble_file,
    struct_unpack_elf_machine,
)


class FakeInsn:
    def __init__(self, address: int, mnemonic: str, op_str: str, raw: bytes) -> None:
        self.address = address
        self.mnemonic = mnemonic
        self.op_str = op_str
        self.bytes = raw


def _elf_header(bits: int, endian: str, sh_off: int, sh_num: int) -> bytes:
    hdr = bytearray(64 if bits == 64 else 52)
    hdr[0:4] = b"\x7fELF"
    hdr[4] = 2 if bits == 64 else 1
    hdr[5] = 1 if endian == "<" else 2
    if bits == 64:
        struct.pack_into(endian + "Q", hdr, 40, sh_off)
        struct.pack_into(endian + "H", hdr, 60, sh_num)
    else:
        struct.pack_into(endian + "I", hdr, 32, sh_off)
        struct.pack_into(endian + "H", hdr, 48, sh_num)
    return bytes(hdr)


def _elf64_section_header(stype: int, s_off: int, s_size: int, endian: str = "<") -> bytes:
    sec = bytearray(64)
    struct.pack_into(endian + "I", sec, 4, stype)
    struct.pack_into(endian + "Q", sec, 24, s_off)
    struct.pack_into(endian + "Q", sec, 32, s_size)
    return bytes(sec)


def _elf32_section_header(stype: int, s_off: int, s_size: int, endian: str = "<") -> bytes:
    sec = bytearray(40)
    struct.pack_into(endian + "I", sec, 4, stype)
    struct.pack_into(endian + "I", sec, 16, s_off)
    struct.pack_into(endian + "I", sec, 20, s_size)
    return bytes(sec)


def _elf64_raw(sh_off: int, sections: list[bytes], endian: str = "<") -> bytes:
    buf = bytearray(sh_off + 64 * len(sections))
    buf[0:64] = _elf_header(64, endian, sh_off, len(sections))
    for i, sec in enumerate(sections):
        start = sh_off + i * 64
        buf[start : start + 64] = sec
    return bytes(buf)


def _elf32_raw(sh_off: int, sections: list[bytes], endian: str = "<") -> bytes:
    buf = bytearray(sh_off + 40 * len(sections))
    buf[0:52] = _elf_header(32, endian, sh_off, len(sections))
    for i, sec in enumerate(sections):
        start = sh_off + i * 40
        buf[start : start + 40] = sec
    return bytes(buf)


def _elf_magic(machine: int, endian: str = "<", bits: int = 64) -> bytes:
    buf = bytearray(64)
    buf[0:4] = b"\x7fELF"
    buf[4] = 2 if bits == 64 else 1
    buf[5] = 1 if endian == "<" else 2
    struct.pack_into(endian + "H", buf, 18, machine)
    return bytes(buf)


def _pe_machine(machine: int) -> bytes:
    pe_off = 0x100
    buf = bytearray(pe_off + 8)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, pe_off)
    struct.pack_into("<H", buf, pe_off + 4, machine)
    return bytes(buf)


def _pe_raw(pe_off: int, sections: list[tuple[bytes, int]]) -> bytes:
    buf = bytearray(pe_off + 248 + 40 * len(sections) + 8)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, pe_off)
    struct.pack_into("<H", buf, pe_off + 6, len(sections))
    for i, (name, ptr) in enumerate(sections):
        off = pe_off + 248 + i * 40
        buf[off : off + len(name)] = name
        struct.pack_into("<I", buf, off + 20, ptr)
    return bytes(buf)


@pytest.fixture
def capstone_module(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake = MagicMock(name="capstone")
    fake.CS_ARCH_X86 = 1
    fake.CS_ARCH_ARM = 2
    fake.CS_ARCH_ARM64 = 3
    fake.CS_ARCH_MIPS = 4
    fake.CS_MODE_32 = 5
    fake.CS_MODE_64 = 6
    fake.CS_MODE_ARM = 7
    fake.CS_MODE_MIPS32 = 8
    fake.CS_MODE_THUMB = 9
    fake.Cs = MagicMock(name="Cs")
    monkeypatch.setitem(sys.modules, "capstone", fake)
    return fake


@pytest.fixture
def fake_elftools(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    elf_cls = MagicMock(name="ELFFile")
    root = MagicMock(name="elftools")
    pkg = MagicMock(name="elftools.elf")
    mod = MagicMock(name="elftools.elf.elffile")
    mod.ELFFile = elf_cls
    monkeypatch.setitem(sys.modules, "elftools", root)
    monkeypatch.setitem(sys.modules, "elftools.elf", pkg)
    monkeypatch.setitem(sys.modules, "elftools.elf.elffile", mod)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: True)
    return elf_cls


def _disasm_capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, str, int]]:
    calls: list[tuple[bytes, str, int]] = []

    def capture(code: bytes, arch: str, offset: int) -> str:
        calls.append((code, arch, offset))
        return "ok"

    monkeypatch.setattr("raven.tools.reverse_engineering.disassembler.disassemble_bytes", capture)
    return calls


class TestDisassembleBytesFallback:
    def test_fallback_used_when_capstone_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "capstone", None)
        out = disassemble_bytes(b"\x90\x90", "x64", 0x400000)
        assert "Capstone not installed" in out
        assert "Architecture: x64, offset: 0x400000, length: 2 bytes" in out

    def test_fallback_header(self) -> None:
        out = _fallback_disassemble(b"\x90", "x64", 0x1000)
        assert "Capstone not installed" in out
        assert "; Showing hex dump instead." in out
        assert "; Architecture: x64, offset: 0x1000, length: 1 bytes" in out

    def test_fallback_hexdump_line(self) -> None:
        out = _fallback_disassemble(b"\x48\x89\xd8\x00\xff\x41", "x64", 0x1000)
        last = out.splitlines()[-1]
        assert "0x00001000" in last
        assert "48 89 d8 00 ff 41" in last
        assert last.endswith("H....A")

    def test_fallback_multiple_rows(self) -> None:
        out = _fallback_disassemble(b"\x00" * 40, "x64", 0x10)
        lines = out.splitlines()
        assert any("0x00000010" in line for line in lines)
        assert any("0x00000020" in line for line in lines)

    def test_fallback_empty_code(self) -> None:
        out = _fallback_disassemble(b"", "arm", 0)
        assert "; Architecture: arm, offset: 0x0, length: 0 bytes" in out
        assert "0x00000000" not in out


class TestDisassembleBytesCapstone:
    @pytest.mark.parametrize(
        ("arch", "cs_arch", "cs_mode"),
        [
            ("x86", 1, 5),
            ("x64", 1, 6),
            ("x86-64", 1, 6),
            ("arm", 2, 7),
            ("arm64", 3, 6),
            ("aarch64", 3, 6),
            ("mips", 4, 8),
            ("thumb", 2, 9),
        ],
    )
    def test_arch_mapping(
        self, capstone_module: MagicMock, arch: str, cs_arch: int, cs_mode: int
    ) -> None:
        capstone_module.Cs.return_value.disasm.return_value = [FakeInsn(0x1000, "nop", "", b"\x90")]
        out = disassemble_bytes(b"\x90", arch)
        assert f"; Disassembly ({arch}) - 1 bytes" in out
        capstone_module.Cs.assert_called_once_with(cs_arch, cs_mode)

    def test_arch_case_insensitive(self, capstone_module: MagicMock) -> None:
        capstone_module.Cs.return_value.disasm.return_value = [FakeInsn(0, "nop", "", b"\x90")]
        out = disassemble_bytes(b"\x90", "X86-64")
        assert "; Disassembly (X86-64) - 1 bytes" in out
        capstone_module.Cs.assert_called_once_with(1, 6)

    def test_unsupported_arch(self, capstone_module: MagicMock) -> None:
        out = disassemble_bytes(b"\x90", "mips64")
        assert out.startswith("[error] Unsupported architecture: mips64")
        assert "Supported: x86, x64, x86-64, arm, arm64, aarch64, mips, thumb" in out
        capstone_module.Cs.assert_not_called()

    def test_init_failure(self, capstone_module: MagicMock) -> None:
        capstone_module.Cs.side_effect = RuntimeError("bad driver")
        out = disassemble_bytes(b"\x90", "x64")
        assert out == "[error] Capstone init failed: bad driver"

    def test_no_instructions_warning(self, capstone_module: MagicMock) -> None:
        capstone_module.Cs.return_value.disasm.return_value = []
        out = disassemble_bytes(b"\x90\x90", "x64")
        assert out == "[warning] No instructions disassembled — wrong architecture?"

    def test_disasm_failure(self, capstone_module: MagicMock) -> None:
        capstone_module.Cs.return_value.disasm.side_effect = ValueError("oops")
        out = disassemble_bytes(b"\x90", "x64")
        assert out == "[error] Disassembly failed: oops"

    def test_enables_detail(self, capstone_module: MagicMock) -> None:
        capstone_module.Cs.return_value.disasm.return_value = []
        disassemble_bytes(b"\x90", "x64")
        assert capstone_module.Cs.return_value.detail is True

    def test_output_formatting(self, capstone_module: MagicMock) -> None:
        capstone_module.Cs.return_value.disasm.return_value = [
            FakeInsn(0x1000, "mov", "rax, rbx", b"\x48\x89\xd8"),
            FakeInsn(0x1003, "ret", "", b"\xc3"),
        ]
        out = disassemble_bytes(b"\x48\x89\xd8\xc3", "x64", 0x1000)
        lines = out.splitlines()
        assert lines[0] == "; Disassembly (x64) - 4 bytes"
        assert lines[1] == "; addr     | bytes            | instruction"
        assert "0x00001000" in lines[2]
        assert "4889d8" in lines[2]
        assert "mov" in lines[2]
        assert "rax, rbx" in lines[2]
        assert "0x00001003" in lines[3]
        assert "c3" in lines[3]


class TestDisassembleFile:
    def test_file_not_found(self, tmp_path: Path) -> None:
        out = disassemble_file(str(tmp_path / "missing.bin"))
        assert out.startswith("[error] File not found:")

    def test_auto_guess(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "prog"
        p.write_bytes(b"\x90\x90\x90")
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.disassembler._guess_arch_from_binary",
            lambda raw: "arm",
        )
        calls = _disasm_capture(monkeypatch)
        assert disassemble_file(str(p)) == "ok"
        assert calls[0][1] == "arm"
        assert calls[0][2] == 0

    def test_auto_no_guess_defaults_x64(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "prog"
        p.write_bytes(b"\x90")
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.disassembler._guess_arch_from_binary",
            lambda raw: None,
        )
        calls = _disasm_capture(monkeypatch)
        assert disassemble_file(str(p)) == "ok"
        assert calls[0][1] == "x64"

    def test_explicit_arch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "prog"
        p.write_bytes(b"\x90")
        calls = _disasm_capture(monkeypatch)
        assert disassemble_file(str(p), arch="mips") == "ok"
        assert calls[0][1] == "mips"

    def test_symbol_extract_error_passthrough(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "prog"
        p.write_bytes(b"\x90")
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.disassembler._extract_code_bytes",
            lambda raw, symbol, size: ("[error] Symbol 'nope' not found", 0),
        )
        out = disassemble_file(str(p), symbol="nope")
        assert out == "[error] Symbol 'nope' not found"

    def test_hex_symbol_offset(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "prog"
        p.write_bytes(bytes(range(256)) * 2)
        calls = _disasm_capture(monkeypatch)
        assert disassemble_file(str(p), symbol="0x10") == "ok"
        assert calls[0][2] == 16
        assert len(calls[0][0]) == 256

    def test_symbol_with_size(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "prog"
        p.write_bytes(bytes(range(256)) * 2)
        calls = _disasm_capture(monkeypatch)
        assert disassemble_file(str(p), symbol="0x10", bytes=8) == "ok"
        assert calls[0][2] == 16
        assert len(calls[0][0]) == 8

    def test_elf_file_default_arch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "prog"
        p.write_bytes(_elf_magic(62))
        calls = _disasm_capture(monkeypatch)
        assert disassemble_file(str(p)) == "ok"
        assert calls[0][1] == "x64"


class TestGuessArchFromBinary:
    @pytest.mark.parametrize(
        ("machine", "expected"),
        [
            (62, "x64"),
            (3, "x86"),
            (40, "arm"),
            (183, "arm64"),
            (8, "mips"),
            (0, "x64"),
            (999, "x64"),
        ],
    )
    def test_elf_machine(self, machine: int, expected: str) -> None:
        assert _guess_arch_from_binary(_elf_magic(machine)) == expected

    def test_elf32_machine(self) -> None:
        assert _guess_arch_from_binary(_elf_magic(3, bits=32)) == "x86"

    def test_truncated_elf_magic(self) -> None:
        assert _guess_arch_from_binary(b"\x7fELF") == "x64"

    @pytest.mark.parametrize(
        ("machine", "expected"),
        [
            (0x8664, "x64"),
            (0x14C, "x86"),
            (0xAA64, "arm64"),
            (0x1C0, "arm"),
            (0x1C4, "arm"),
            (0x100, "x64"),
        ],
    )
    def test_pe_machine(self, machine: int, expected: str) -> None:
        assert _guess_arch_from_binary(_pe_machine(machine)) == expected

    def test_pe_machine_detect_failure(self) -> None:
        assert _guess_arch_from_binary(b"MZ") == "x64"

    def test_unknown_format(self) -> None:
        assert _guess_arch_from_binary(b"\x00\x01\x02\x03\x04") is None


class TestStructUnpackElfMachine:
    def test_little_endian(self) -> None:
        raw = bytearray(20)
        raw[0:4] = b"\x7fELF"
        raw[4] = 2
        raw[5] = 1
        struct.pack_into("<H", raw, 18, 62)
        assert struct_unpack_elf_machine(bytes(raw)) == 62

    def test_big_endian(self) -> None:
        raw = bytearray(20)
        raw[0:4] = b"\x7fELF"
        raw[4] = 2
        raw[5] = 2
        struct.pack_into(">H", raw, 18, 183)
        assert struct_unpack_elf_machine(bytes(raw)) == 183

    def test_short_input(self) -> None:
        assert struct_unpack_elf_machine(b"\x7fELF") == 0

    def test_header_too_short(self) -> None:
        assert struct_unpack_elf_machine(b"\x7fELF\x02\x01" + b"\x00" * 12) == 0


class TestExtractCodeBytes:
    def test_symbol_hex_address(self) -> None:
        raw = b"\x00" * 300
        code, offset = _extract_code_bytes(raw, "0x10", 0)
        assert offset == 16
        assert code == raw[16:272]

    def test_symbol_decimal_address(self) -> None:
        raw = b"\x00" * 300
        code, offset = _extract_code_bytes(raw, "16", 0)
        assert offset == 16
        assert code == raw[16:272]

    def test_symbol_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: False)
        code, offset = _extract_code_bytes(b"\x00" * 16, "does_not_exist", 0)
        assert offset == 0
        assert isinstance(code, str)
        assert "does_not_exist" in code

    def test_symbol_with_size(self) -> None:
        raw = b"\x01" * 300
        code, offset = _extract_code_bytes(raw, "0x20", 8)
        assert offset == 32
        assert code == raw[32:40]

    def test_text_section_default_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = b"\x02" * 5000
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.disassembler._find_text_section", lambda r: 100
        )
        code, offset = _extract_code_bytes(raw, "", 0)
        assert offset == 100
        assert len(code) == 4096
        assert code == raw[100:4196]

    def test_text_section_with_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = b"\x02" * 5000
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.disassembler._find_text_section", lambda r: 100
        )
        code, offset = _extract_code_bytes(raw, "", 8)
        assert offset == 100
        assert code == raw[100:108]

    def test_no_text_section_with_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = b"\x03" * 100
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.disassembler._find_text_section", lambda r: None
        )
        code, offset = _extract_code_bytes(raw, "", 4)
        assert offset == 0
        assert code == raw[:4]

    def test_no_text_section_default_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        raw = b"\x03" * 100
        monkeypatch.setattr(
            "raven.tools.reverse_engineering.disassembler._find_text_section", lambda r: None
        )
        code, offset = _extract_code_bytes(raw, "", 0)
        assert offset == 0
        assert code == raw[:100]


class TestResolveSymbol:
    def test_hex_address(self) -> None:
        assert _resolve_symbol(b"\x00" * 16, "0x1a2b") == 0x1A2B

    def test_decimal_address(self) -> None:
        assert _resolve_symbol(b"\x00" * 16, "42") == 42

    def test_no_elftools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: False)
        assert _resolve_symbol(b"\x00" * 16, "main") is None

    def test_symbol_found(self, fake_elftools: MagicMock) -> None:
        sym = MagicMock(name="symbol")
        sym.name = "main"
        sym.entry.st_value = 0x401000
        fake_elftools.return_value.iter_sections.return_value = [
            MagicMock(iter_symbols=lambda: [sym])
        ]
        assert _resolve_symbol(b"\x00" * 16, "main") == 0x401000

    def test_symbol_missing(self, fake_elftools: MagicMock) -> None:
        sym = MagicMock(name="symbol")
        sym.name = "other"
        sym.entry.st_value = 0x1000
        fake_elftools.return_value.iter_sections.return_value = [
            MagicMock(iter_symbols=lambda: [sym])
        ]
        assert _resolve_symbol(b"\x00" * 16, "main") is None

    def test_elf_parse_error(self, fake_elftools: MagicMock) -> None:
        fake_elftools.return_value.iter_sections.side_effect = ValueError("corrupt elf")
        assert _resolve_symbol(b"\x00" * 16, "main") is None


class TestFindTextSection:
    def test_elf64_little_endian(self) -> None:
        raw = _elf64_raw(0x100, [_elf64_section_header(1, 0x200, 0x100)])
        assert _find_text_section(raw) == 0x200

    def test_elf64_big_endian(self) -> None:
        raw = _elf64_raw(0x100, [_elf64_section_header(1, 0x200, 0x100, ">")], ">")
        assert _find_text_section(raw) == 0x200

    def test_elf64_multiple_sections(self) -> None:
        raw = _elf64_raw(
            0x100,
            [
                _elf64_section_header(2, 0x200, 0x100),
                _elf64_section_header(1, 0x300, 0x50),
            ],
        )
        assert _find_text_section(raw) == 0x300

    def test_elf64_no_progbits(self) -> None:
        raw = _elf64_raw(0x100, [_elf64_section_header(2, 0x200, 0x100)])
        assert _find_text_section(raw) is None

    def test_elf64_section_table_out_of_bounds(self) -> None:
        raw = _elf_header(64, "<", 0x1000, 1)
        assert _find_text_section(raw) is None

    def test_elf32_little_endian(self) -> None:
        raw = _elf32_raw(0x100, [_elf32_section_header(1, 0x200, 0x100)])
        assert _find_text_section(raw) == 0x200

    def test_elf32_big_endian(self) -> None:
        raw = _elf32_raw(0x100, [_elf32_section_header(1, 0x200, 0x100, ">")], ">")
        assert _find_text_section(raw) == 0x200

    def test_elf_truncated_magic(self) -> None:
        assert _find_text_section(b"\x7fELF") is None

    def test_pe_found(self) -> None:
        raw = _pe_raw(0x100, [(b".text\x00\x00\x00", 0x1000)])
        assert _find_text_section(raw) == 0x1000

    def test_pe_no_text(self) -> None:
        raw = _pe_raw(0x100, [(b".data\x00\x00\x00", 0x2000)])
        assert _find_text_section(raw) is None

    def test_pe_truncated(self) -> None:
        assert _find_text_section(b"MZ") is None

    def test_pe_bogus_pe_offset(self) -> None:
        raw = bytearray(128)
        raw[0:2] = b"MZ"
        struct.pack_into("<I", raw, 0x3C, 0xFFFFFFFF)
        assert _find_text_section(bytes(raw)) is None

    def test_unknown_format(self) -> None:
        assert _find_text_section(b"\x00\x01\x02") is None

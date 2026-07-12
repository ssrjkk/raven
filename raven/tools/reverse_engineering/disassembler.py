from __future__ import annotations

import re
from pathlib import Path

from loguru import logger


async def disassemble_bytes(code: bytes, arch: str = "x64", offset: int = 0) -> str:
    try:
        from capstone import (
            CS_ARCH_ARM,
            CS_ARCH_ARM64,
            CS_ARCH_MIPS,
            CS_ARCH_X86,
            CS_MODE_32,
            CS_MODE_64,
            CS_MODE_ARM,
            CS_MODE_MIPS32,
            CS_MODE_THUMB,
            Cs,
        )
    except ImportError:
        return _fallback_disassemble(code, arch, offset)

    arch_map = {
        "x86": (CS_ARCH_X86, CS_MODE_32),
        "x64": (CS_ARCH_X86, CS_MODE_64),
        "x86-64": (CS_ARCH_X86, CS_MODE_64),
        "arm": (CS_ARCH_ARM, CS_MODE_ARM),
        "arm64": (CS_ARCH_ARM64, CS_MODE_64),
        "aarch64": (CS_ARCH_ARM64, CS_MODE_64),
        "mips": (CS_ARCH_MIPS, CS_MODE_MIPS32),
        "thumb": (CS_ARCH_ARM, CS_MODE_THUMB),
    }
    key = arch.lower().replace(" ", "-")
    if key not in arch_map:
        return f"[error] Unsupported architecture: {arch}. Supported: {', '.join(arch_map)}"

    cs_arch, cs_mode = arch_map[key]
    try:
        md = Cs(cs_arch, cs_mode)
        md.detail = True
    except Exception as e:
        return f"[error] Capstone init failed: {e}"

    lines = [f"; Disassembly ({arch}) - {len(code)} bytes", "; addr     | bytes            | instruction"]
    try:
        for insn in md.disasm(code, offset):
            bytes_hex = insn.bytes.hex() if hasattr(insn.bytes, "hex") else insn.bytes.hex()
            op_str = insn.op_str if insn.op_str else ""
            lines.append(f"  {insn.address:#010x}  {bytes_hex:20s} {insn.mnemonic:8s} {op_str}")

        if len(lines) == 1:
            return "[warning] No instructions disassembled — wrong architecture?"
        return "\n".join(lines)
    except Exception as e:
        return f"[error] Disassembly failed: {e}"


async def disassemble_file(path: str, symbol: str = "", bytes: int = 0, arch: str = "auto") -> str:
    p = Path(path)
    if not p.exists():
        return f"[error] File not found: {path}"

    raw = p.read_bytes()

    if arch == "auto":
        guessed = _guess_arch_from_binary(raw)
        if guessed:
            arch = guessed
        else:
            arch = "x64"

    code, offset = _extract_code_bytes(raw, symbol, bytes)
    if isinstance(code, str):
        return code

    result = await disassemble_bytes(code, arch, offset)
    return result


def _guess_arch_from_binary(raw: bytes) -> str | None:
    if raw[:4] == b"\x7fELF":
        raw[4]
        machine = struct_unpack_elf_machine(raw)
        if machine == 62:
            return "x64"
        elif machine == 3:
            return "x86"
        elif machine == 40 or machine == 0x28:
            return "arm"
        elif machine == 183:
            return "arm64"
        elif machine == 8:
            return "mips"
        return "x64"
    if raw[:2] == b"MZ":
        pe_off = 0
        try:
            import struct

            pe_off = struct.unpack("<I", raw[0x3C:0x40])[0]
            machine = struct.unpack("<H", raw[pe_off + 4 : pe_off + 6])[0]
        except Exception:
            machine = 0
        if machine == 0x8664:
            return "x64"
        elif machine == 0x14C:
            return "x86"
        elif machine == 0xAA64:
            return "arm64"
        elif machine in (0x1C0, 0x1C4):
            return "arm"
        return "x64"
    return None


def struct_unpack_elf_machine(raw: bytes) -> int:
    import struct

    ei_class = raw[4] if len(raw) > 4 else 1
    endian = "<" if raw[5] == 1 else ">"
    offset = 18 if ei_class == 2 else 18
    if offset + 2 <= len(raw):
        return int(struct.unpack(endian + "H", raw[offset : offset + 2])[0])
    return 0


def _extract_code_bytes(raw: bytes, symbol: str, size: int) -> tuple[bytes | str, int]:

    if symbol:
        addr = _resolve_symbol(raw, symbol)
        if addr is None:
            return f"[error] Symbol '{symbol}' not found", 0
        offset = addr
        length = size if size > 0 else 256
        return raw[offset : offset + length], offset

    text_start = _find_text_section(raw)
    if text_start is not None:
        if size > 0:
            return raw[text_start : text_start + size], text_start
        return raw[text_start : text_start + min(4096, len(raw) - text_start)], text_start

    if size > 0:
        return raw[:size], 0
    return raw[:4096], 0


def _resolve_symbol(raw: bytes, symbol: str) -> int | None:
    if re.match(r"^0x[0-9a-fA-F]+$", symbol):
        return int(symbol, 16)
    if re.match(r"^\d+$", symbol):
        return int(symbol)

    import importlib.util

    if not importlib.util.find_spec("elftools"):
        return None
    try:
        import io

        from elftools.elf.elffile import ELFFile

        f = io.BytesIO(raw)
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            if hasattr(sec, "iter_symbols"):
                for sym in sec.iter_symbols():
                    if sym.name == symbol:
                        return int(sym.entry.st_value)
    except Exception as e:
        logger.debug("Symbol resolution failed: {}", e)
    return None


def _find_text_section(raw: bytes) -> int | None:
    import struct

    if raw[:4] == b"\x7fELF":
        bits = 64 if raw[4] == 2 else 32
        endian_fmt = "<" if raw[5] == 1 else ">"
        if bits == 64:
            sh_off = struct.unpack(endian_fmt + "Q", raw[40:48])[0]
            sh_num = struct.unpack(endian_fmt + "H", raw[60:62])[0]
            shent_size = 64
        else:
            sh_off = struct.unpack(endian_fmt + "I", raw[32:36])[0]
            sh_num = struct.unpack(endian_fmt + "H", raw[48:50])[0]
            shent_size = 40

        for i in range(min(sh_num, 100)):
            off = sh_off + i * shent_size
            if off + shent_size > len(raw):
                break
            if bits == 64:
                stype = struct.unpack(endian_fmt + "I", raw[off + 4 : off + 8])[0]
                soff = struct.unpack(endian_fmt + "Q", raw[off + 24 : off + 32])[0]
                ssize = struct.unpack(endian_fmt + "Q", raw[off + 32 : off + 40])[0]
            else:
                stype = struct.unpack(endian_fmt + "I", raw[off + 4 : off + 8])[0]
                soff = struct.unpack(endian_fmt + "I", raw[off + 16 : off + 20])[0]
                ssize = struct.unpack(endian_fmt + "I", raw[off + 20 : off + 24])[0]
            if stype == 1 and ssize > 0:
                return int(soff)

    elif raw[:2] == b"MZ":
        try:
            pe_off = struct.unpack("<I", raw[0x3C:0x40])[0]
            num_sections = struct.unpack("<H", raw[pe_off + 6 : pe_off + 8])[0]
            sect_off = pe_off + 248
            for i in range(min(num_sections, 100)):
                off = sect_off + i * 40
                name = raw[off : off + 8].split(b"\x00")[0].decode("ascii", errors="replace")
                if name.lower() == ".text":
                    raw_ptr: int = struct.unpack("<I", raw[off + 20 : off + 24])[0]
                    return raw_ptr
        except Exception:
            return None
    return None


def _fallback_disassemble(code: bytes, arch: str, offset: int) -> str:
    lines = [
        "; Capstone not installed. Install with: pip install capstone",
        "; Showing hex dump instead.",
        f"; Architecture: {arch}, offset: {offset:#x}, length: {len(code)} bytes",
        "",
    ]
    for i in range(0, len(code), 16):
        chunk = code[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
        lines.append(f"  {offset + i:#010x}  {hex_part:48s}  {ascii_part}")
    return "\n".join(lines)

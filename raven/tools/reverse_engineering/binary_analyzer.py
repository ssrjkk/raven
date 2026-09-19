from __future__ import annotations

import re
import struct
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger


def get_file_type(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"error": f"File not found: {path}"}
    if not p.is_file():
        return {"error": f"Not a file: {path}"}

    size = p.stat().st_size
    raw = p.read_bytes()[:512]
    info: dict[str, Any] = {
        "file_name": p.name,
        "size": size,
        "size_human": _format_size(size),
    }

    if raw[:4] == b"\x7fELF":
        info["type"] = "ELF"
        info["bits"] = 64 if raw[4] == 2 else 32
        endian = "little" if raw[5] == 1 else "big"
        info["endian"] = endian
        e_type_map = {0: "NONE", 1: "REL", 2: "EXEC", 3: "DYN", 4: "CORE"}
        e_machine_map = {
            0: "None",
            2: "SPARC",
            3: "x86",
            8: "MIPS",
            20: "PowerPC",
            40: "ARM",
            43: "SPARCv9",
            50: "IA-64",
            62: "x86-64",
            183: "AArch64",
            243: "RISC-V",
            253: "BPF",
        }
        offset = 16
        e_type = struct.unpack("<H" if endian == "little" else ">H", raw[offset : offset + 2])[0]
        e_machine = struct.unpack("<H" if endian == "little" else ">H", raw[offset + 2 : offset + 4])[0]
        info["file_type"] = e_type_map.get(e_type, f"unknown({e_type})")
        info["architecture"] = e_machine_map.get(e_machine, f"unknown({e_machine})")

    elif raw[:2] == b"MZ":
        info["type"] = "PE"
        pe_offset = struct.unpack("<I", raw[0x3C : 0x3C + 4])[0]
        if pe_offset + 4 < len(raw) and raw[pe_offset : pe_offset + 4] == b"PE\x00\x00":
            machine_id = struct.unpack("<H", raw[pe_offset + 4 : pe_offset + 6])[0]
            machine_map = {
                0x14C: "x86 (I386)",
                0x8664: "x86-64 (AMD64)",
                0x1C0: "ARMv7",
                0xAA64: "ARM64 (AArch64)",
                0x1C4: "ARMv7 Thumb",
            }
            info["architecture"] = machine_map.get(machine_id, f"unknown(0x{machine_id:04x})")
            characteristics = struct.unpack("<H", raw[pe_offset + 18 : pe_offset + 20])[0]
            if characteristics & 0x2000:
                info["subsystem"] = "DLL"
            elif characteristics & 0x0002:
                info["subsystem"] = "EXE"

            timestamp = struct.unpack("<I", raw[pe_offset + 8 : pe_offset + 12])[0]
            if timestamp:
                info["timestamp"] = _pe_timestamp(timestamp)

            opt_magic = struct.unpack("<H", raw[pe_offset + 24 : pe_offset + 26])[0]
            if opt_magic in (0x10B, 0x20B):
                entry_rva = struct.unpack("<I", raw[pe_offset + 40 : pe_offset + 44])[0]
                if entry_rva:
                    info["entry_point"] = hex(entry_rva)
                image_base = struct.unpack("<I", raw[pe_offset + 52 : pe_offset + 56])[0]
                if opt_magic == 0x20B:
                    image_base = struct.unpack("<Q", raw[pe_offset + 48 : pe_offset + 56])[0]
                info["image_base"] = hex(image_base)

    elif raw[:4] in (b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
        info["type"] = "Mach-O"
        _parse_macho_header(raw, info)

    elif raw[:4] == b"\xca\xfe\xba\xbe":
        info["type"] = "Universal Mach-O (Fat Binary)"

    else:
        info["type"] = "Unknown"
        info["notes"] = "Could not determine file format"

    return info


def _format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


_MACHO_CPU_TYPES: dict[int, str] = {
    1: "VAX",
    6: "MC680x0",
    7: "i386",
    10: "MC98000",
    11: "HPPA",
    12: "ARM",
    13: "MC88000",
    14: "SPARC",
    15: "I860",
    18: "PowerPC",
    0x01000007: "x86-64",
    0x0100000C: "arm64",
    0x01000012: "PowerPC64",
}

_MACHO_FILETYPES: dict[int, str] = {
    1: "MH_OBJECT",
    2: "MH_EXECUTE",
    3: "MH_FVMLIB",
    4: "MH_CORE",
    5: "MH_PRELOAD",
    6: "MH_DYLIB",
    7: "MH_DYLINKER",
    8: "MH_BUNDLE",
    9: "MH_DYLIB_STUB",
    10: "MH_DSYM",
    11: "MH_KEXT_BUNDLE",
}


def _parse_macho_header(raw: bytes, info: dict[str, Any]) -> None:
    magic = raw[:4]
    is_64 = magic in (b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe")
    endian = "<" if magic in (b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe") else ">"
    info["bits"] = 64 if is_64 else 32
    info["endian"] = "little" if endian == "<" else "big"
    if len(raw) < 28:
        return
    cputype = struct.unpack(endian + "I", raw[4:8])[0]
    filetype = struct.unpack(endian + "I", raw[12:16])[0]
    ncmds = struct.unpack(endian + "I", raw[16:20])[0]
    flags = struct.unpack(endian + "I", raw[24:28])[0]
    info["architecture"] = _MACHO_CPU_TYPES.get(cputype, f"unknown(0x{cputype:x})")
    info["file_type"] = _MACHO_FILETYPES.get(filetype, f"unknown({filetype})")
    info["load_commands"] = ncmds
    if flags & 0x200000:
        info["pie"] = True
    elif flags & 0x4:
        info["dylib"] = True


def _pe_timestamp(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OverflowError, OSError, ValueError):
        return f"0x{ts:x}"


def _try_pyelftools(path: str) -> dict[str, Any] | None:
    import importlib.util

    if not importlib.util.find_spec("elftools"):
        return None
    try:
        from elftools.elf.elffile import ELFFile

        with Path(path).open("rb") as f:
            elf = ELFFile(f)
            sections = []
            for sec in elf.iter_sections():
                s = {"name": sec.name, "type": str(sec.header.sh_type), "size": sec.header.sh_size}
                try:
                    s["addr"] = hex(sec.header.sh_addr)
                except Exception as e:
                    logger.debug("Section addr extraction failed: {}", e)
                    s["addr"] = "0x0"
                try:
                    data = sec.data()
                    if data:
                        s["entropy"] = _calculate_entropy(data)
                except Exception as e:
                    logger.debug("Section entropy failed: {}", e)
                sections.append(s)
            symbols = []
            if hasattr(elf, "get_section_by_name") and elf.get_section_by_name(".symtab"):
                symtab = elf.get_section_by_name(".symtab")
                for sym in symtab.iter_symbols():
                    symbols.append(
                        {
                            "name": sym.name,
                            "value": hex(sym.entry.st_value),
                            "size": sym.entry.st_size,
                        }
                    )
            return {"sections": sections, "symbols": symbols[:500]}
    except Exception as e:
        return {"error": str(e)}


def _try_pefile(path: str) -> dict[str, Any] | None:
    try:
        import pefile
    except ImportError:
        return None
    try:
        pe = pefile.PE(path)
        imports = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for entry in pe.DIRECTORY_ENTRY_IMPORT:
                dll_name = (
                    entry.dll.decode("utf-8", errors="replace") if isinstance(entry.dll, bytes) else str(entry.dll)
                )
                for imp in entry.imports:
                    name = imp.name.decode("utf-8", errors="replace") if imp.name else f"ord({imp.ordinal})"
                    imports.append({"dll": dll_name, "name": name, "address": hex(imp.address)})

        exports = []
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                name = exp.name.decode("utf-8", errors="replace") if exp.name else f"ord({exp.ordinal})"
                exports.append({"name": name, "address": hex(exp.address)})

        sections = []
        for sec in pe.sections:
            name = sec.Name.decode("utf-8", errors="replace").rstrip("\x00")
            sections.append(
                {
                    "name": name,
                    "vaddr": hex(sec.VirtualAddress),
                    "vsize": sec.Misc_VirtualSize,
                    "raw_size": sec.SizeOfRawData,
                    "entropy": sec.get_entropy(),
                }
            )

        return {"imports": imports[:300], "exports": exports[:100], "sections": sections}
    except Exception as e:
        return {"error": str(e)}


def _raw_pe_imports(raw: bytes, pe_offset: int) -> list[dict[str, Any]]:
    """Fallback PE import parser when pefile is unavailable.

    Walks the import directory table directly: DLL names + thunk-resolved
    function names (with ordinal fallback). Returns [] when the section
    layout cannot be mapped to a file offset (packed/bin is raw anyway).
    """
    try:
        num_sections = struct.unpack("<H", raw[pe_offset + 6 : pe_offset + 8])[0]
        opt_size = struct.unpack("<H", raw[pe_offset + 20 : pe_offset + 22])[0]
        opt_offset = pe_offset + 24
        magic = struct.unpack("<H", raw[opt_offset : opt_offset + 2])[0]
        if magic not in (0x10B, 0x20B) or opt_size < 96:
            return []
        bits = 64 if magic == 0x20B else 32
        import_rva = struct.unpack("<I", raw[opt_offset + 0x68 : opt_offset + 0x6C])[0]
        if not import_rva:
            return []

        sections: list[tuple[int, int, int]] = []
        sect_hdr_off = opt_offset + opt_size
        for i in range(num_sections):
            off = sect_hdr_off + i * 40
            if off + 40 > len(raw):
                break
            vaddr = struct.unpack("<I", raw[off + 12 : off + 16])[0]
            raw_size = struct.unpack("<I", raw[off + 16 : off + 20])[0]
            raw_ptr = struct.unpack("<I", raw[off + 20 : off + 24])[0]
            vsize = struct.unpack("<I", raw[off + 8 : off + 12])[0]
            sections.append((vaddr, vsize if vsize else raw_size, raw_ptr))

        def _rva_to_off(rva: int) -> int | None:
            for vaddr, vsize, raw_ptr in sections:
                if vaddr <= rva < vaddr + max(vsize, 1):
                    return raw_ptr + (rva - vaddr)
            return None

        thunk_size = 8 if bits == 64 else 4

        def _read_cstring(off: int) -> str:
            end = raw.find(b"\x00", off)
            if end == -1:
                end = min(off + 128, len(raw))
            return raw[off:end].decode("utf-8", errors="replace")

        imports: list[dict[str, Any]] = []
        desc_off = _rva_to_off(import_rva)
        if desc_off is None:
            return []
        seen: set[tuple[str, str]] = set()
        for entry_idx in range(64):
            entry_off = desc_off + entry_idx * 20
            if entry_off + 20 > len(raw):
                break
            orig_thunk = struct.unpack("<I", raw[entry_off : entry_off + 4])[0]
            name_rva = struct.unpack("<I", raw[entry_off + 12 : entry_off + 16])[0]
            first_thunk = struct.unpack("<I", raw[entry_off + 16 : entry_off + 20])[0]
            if not name_rva:
                break
            dll_off = _rva_to_off(name_rva)
            if dll_off is None:
                continue
            dll = _read_cstring(dll_off)
            thunk_rva = orig_thunk or first_thunk
            thunk_off = _rva_to_off(thunk_rva)
            for _thunk_idx in range(4096):
                if thunk_off is None or thunk_off + thunk_size > len(raw):
                    break
                if bits == 64:
                    val = struct.unpack("<Q", raw[thunk_off : thunk_off + 8])[0]
                else:
                    val = struct.unpack("<I", raw[thunk_off : thunk_off + 4])[0]
                if val == 0:
                    break
                ordinal = bool(val & (1 << (bits - 1)))
                if ordinal:
                    name = f"ord({val & 0xFFFF})"
                else:
                    iname_off = _rva_to_off(val & 0x7FFFFFFF)
                    if iname_off is None or iname_off + 3 > len(raw):
                        name = "ord(?)"
                    else:
                        name = _read_cstring(iname_off + 2)
                key = (dll, name)
                if key not in seen:
                    seen.add(key)
                    imports.append({"dll": dll, "name": name, "address": hex(val)})
                thunk_off += thunk_size
        return imports
    except Exception as e:
        logger.debug("raw PE import fallback failed: {}", e)
        return []


def _parse_elf_raw(raw: bytes, info: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    bits = info.get("bits", 64)
    endian = info.get("endian", "little")
    endian_fmt = "<" if endian == "little" else ">"

    if bits == 64:
        entry = struct.unpack(endian_fmt + "Q", raw[24:32])[0]
        sh_off = struct.unpack(endian_fmt + "Q", raw[40:48])[0]
        ph_num = struct.unpack(endian_fmt + "H", raw[54:56])[0]
        sh_num = struct.unpack(endian_fmt + "H", raw[60:62])[0]
    else:
        entry = struct.unpack(endian_fmt + "I", raw[24:28])[0]
        sh_off = struct.unpack(endian_fmt + "I", raw[32:36])[0]
        ph_num = struct.unpack(endian_fmt + "H", raw[44:46])[0]
        sh_num = struct.unpack(endian_fmt + "H", raw[48:50])[0]

    if entry:
        result["entry_point"] = hex(entry)
    result["segment_count"] = ph_num
    result["section_count"] = sh_num

    text_offset = _find_text_section_offset(raw, sh_off, sh_num, endian_fmt, bits)
    if text_offset:
        result[".text_offset"] = hex(text_offset)

    return result


def _find_text_section_offset(raw: bytes, sh_off: int, sh_num: int, endian_fmt: str, bits: int) -> int | None:
    shent_size = 64 if bits == 64 else 40
    for i in range(min(sh_num, 100)):
        offset = sh_off + i * shent_size
        if offset + shent_size > len(raw):
            break
        if bits == 64:
            struct.unpack(endian_fmt + "I", raw[offset : offset + 4])[0]
            sh_type = struct.unpack(endian_fmt + "I", raw[offset + 4 : offset + 8])[0]
            sh_offset = struct.unpack(endian_fmt + "Q", raw[offset + 24 : offset + 32])[0]
            sh_size = struct.unpack(endian_fmt + "Q", raw[offset + 32 : offset + 40])[0]
        else:
            struct.unpack(endian_fmt + "I", raw[offset : offset + 4])[0]
            sh_type = struct.unpack(endian_fmt + "I", raw[offset + 4 : offset + 8])[0]
            sh_offset = struct.unpack(endian_fmt + "I", raw[offset + 16 : offset + 20])[0]
            sh_size = struct.unpack(endian_fmt + "I", raw[offset + 20 : offset + 24])[0]

        if sh_type == 1 and sh_size > 0:
            return int(sh_offset)
    return None


def _find_pe_text_section(raw: bytes, pe_offset: int) -> int | None:
    try:
        num_sections = struct.unpack("<H", raw[pe_offset + 6 : pe_offset + 8])[0]
        sect_hdr_off = pe_offset + 248
        for i in range(min(num_sections, 100)):
            off = sect_hdr_off + i * 40
            if off + 40 > len(raw):
                break
            name = raw[off : off + 8].split(b"\x00")[0].decode("ascii", errors="replace")
            if name.lower() == ".text":
                raw_ptr = struct.unpack("<I", raw[off + 20 : off + 24])[0]
                return int(raw_ptr)
    except Exception as e:
        logger.warning("PE .text section lookup failed: {}", e)
    return None


def analyze_binary(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"[error] File not found: {path}"

    file_type = get_file_type(path)
    if "error" in file_type:
        return f"[error] {file_type['error']}"

    raw = p.read_bytes()
    lines = [
        f"=== Analysis: {file_type['file_name']} ===",
        f"  Size: {file_type['size_human']} ({file_type['size']} bytes)",
        f"  Format: {file_type.get('type', '?')}",
    ]
    if "architecture" in file_type:
        lines.append(f"  Architecture: {file_type['architecture']}")
    if "file_type" in file_type:
        lines.append(f"  Type: {file_type['file_type']}")
    if "subsystem" in file_type:
        lines.append(f"  Subsystem: {file_type['subsystem']}")
    if "endian" in file_type:
        lines.append(f"  Endian: {file_type['endian']}")
    if "entry_point" in file_type:
        lines.append(f"  Entry point: {file_type['entry_point']}")
    if "image_base" in file_type:
        lines.append(f"  Image base: {file_type['image_base']}")
    if "timestamp" in file_type:
        lines.append(f"  Compile time: {file_type['timestamp']}")
    if "load_commands" in file_type:
        lines.append(f"  Load commands: {file_type['load_commands']}")

    ft = file_type.get("type", "")
    if ft == "ELF":
        elf_info = _try_pyelftools(str(p))
        if elf_info:
            if "sections" in elf_info:
                lines.append(f"\n  Sections ({len(elf_info['sections'])}):")
                for s in elf_info["sections"][:30]:
                    entropy = f"entropy={s['entropy']:.2f}" if "entropy" in s else "entropy=?"
                    lines.append(f"    {s['name']:20s} addr={s.get('addr', '?'):14s} size={s['size']}  {entropy}")
            if "symbols" in elf_info:
                lines.append(f"\n  Symbols ({len(elf_info['symbols'])}):")
                for s in elf_info["symbols"][:20]:
                    lines.append(f"    {s['value']:18s} {s['name']}")
        else:
            raw_info = _parse_elf_raw(raw, file_type)
            if "segment_count" in raw_info:
                lines.append(f"\n  Segments: {raw_info['segment_count']}")
                lines.append(f"  Sections: {raw_info['section_count']}")
                if "entry_point" in raw_info:
                    lines.append(f"  Entry point: {raw_info['entry_point']}")

    elif ft == "PE":
        pe_info = _try_pefile(str(p))
        if pe_info:
            if "sections" in pe_info:
                lines.append(f"\n  Sections ({len(pe_info['sections'])}):")
                for s in pe_info["sections"]:
                    lines.append(
                        f"    {s['name']:12s} vaddr={s['vaddr']} vsize={s['vsize']:>8}  entropy={s['entropy']:.2f}"
                    )
            if "imports" in pe_info:
                lines.append(f"\n  Imports ({len(pe_info['imports'])}):")
                for imp in pe_info["imports"][:30]:
                    lines.append(f"    {imp['dll']}!{imp['name']} -> {imp['address']}")
            if "exports" in pe_info:
                lines.append(f"\n  Exports ({len(pe_info['exports'])}):")
                for exp in pe_info["exports"][:10]:
                    lines.append(f"    {exp['name']} -> {exp['address']}")
        else:
            pe_off = struct.unpack("<I", raw[0x3C : 0x3C + 4])[0]
            text_off = _find_pe_text_section(raw, pe_off)
            if text_off:
                lines.append(f"\n  .text at raw offset: {hex(text_off)}")
            fallback_imports = _raw_pe_imports(raw, pe_off)
            if fallback_imports:
                lines.append(f"\n  Imports (raw fallback, {len(fallback_imports)}):")
                for imp in fallback_imports[:30]:
                    lines.append(f"    {imp['dll']}!{imp['name']} -> {imp['address']}")
    else:
        lines.append("\n  (detailed parsing requires pyelftools or pefile)")

    lines.append(f"\n  Entropy: {_calculate_entropy(raw):.3f}")
    lines.append(f"  Strings found: {_count_strings(raw)}")
    lines.append(f"  Unicode strings: {_count_unicode_strings(raw)}")

    return "\n".join(lines)


def extract_strings(path: str, min_length: int = 4, classify: bool = False) -> str:
    p = Path(path)
    if not p.exists():
        return f"[error] File not found: {path}"
    raw = p.read_bytes()

    ascii_strings = re.findall(rb"[\x20-\x7e]{" + str(min_length).encode() + rb",}", raw)
    unicode_strings = re.findall(rb"(?:[\x20-\x7e]\x00){" + str(min_length).encode() + rb",}", raw)
    unicode_decoded = [s.decode("utf-16-le", errors="replace") for s in unicode_strings]

    classified: dict[str, list[str]] = {
        "urls": [],
        "paths": [],
        "crypto": [],
        "ip": [],
        "function_names": [],
        "registry": [],
        "other": [],
    }

    all_strings = [s.decode("ascii", errors="replace") for s in ascii_strings]
    all_strings.extend(unicode_decoded)
    all_strings = sorted(set(all_strings))

    if classify:
        for s in all_strings:
            if re.match(r"https?://", s, re.IGNORECASE):
                classified["urls"].append(s)
            elif s.startswith(("HKLM", "HKCU", "HKEY")):
                classified["registry"].append(s)
            elif re.match(r"[a-zA-Z]:[\\/]", s) or s.startswith(("/", "./")) or "\\" in s:
                classified["paths"].append(s)
            elif re.match(r"^[A-Fa-f0-9]{32,64}$", s):
                classified["crypto"].append(s[:64])
            elif re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", s):
                classified["ip"].append(s)
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s) and 2 < len(s) < 60:
                classified["function_names"].append(s)
            else:
                classified["other"].append(s)

    if classify:
        lines = [f"=== Strings from {p.name} (min_length={min_length}) ==="]
        for cat, items in classified.items():
            if items:
                lines.append(f"\n  [{cat}] ({len(items)}):")
                for item in items[:50]:
                    lines.append(f"    {item[:120]}")
                if len(items) > 50:
                    lines.append(f"    ... and {len(items) - 50} more")
        return "\n".join(lines)

    lines = [f"=== Strings from {p.name} (min_length={min_length}) ==="]
    lines.append(f"  ASCII strings: {len(ascii_strings)}")
    lines.append(f"  Unicode strings: {len(unicode_strings)}")
    lines.append("")
    for s in all_strings[:200]:
        lines.append(f"  {s[:150]}")
    if len(all_strings) > 200:
        lines.append(f"  ... and {len(all_strings) - 200} more")
    return "\n".join(lines)


def _calculate_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    from math import log2

    n = len(data)
    entropy = 0.0
    for count in Counter(data).values():
        p = count / n
        entropy += -p * log2(p)
    return entropy


def _count_strings(data: bytes) -> int:
    return len(re.findall(rb"[\x20-\x7e]{4,}", data))


def _count_unicode_strings(data: bytes) -> int:
    return len(re.findall(rb"(?:[\x20-\x7e]\x00){4,}", data))


def hexdump(path: str, offset: int = 0, length: int = 256) -> str:
    p = Path(path)
    if not p.exists():
        return f"[error] File not found: {path}"
    size = p.stat().st_size
    if offset < 0 or offset >= size:
        return f"[error] Offset {offset} out of range (file size {size})"
    with p.open("rb") as f:
        if offset:
            f.seek(offset)
        data = f.read(length)

    lines = [f"; hexdump {p.name} @0x{offset:x} ({len(data)} bytes)"]
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
        lines.append(f"  {offset + i:#010x}  {hex_part:48s}  {ascii_part}")
    return "\n".join(lines)


def hash_binary(path: str) -> str:
    import hashlib

    p = Path(path)
    if not p.exists():
        return f"[error] File not found: {path}"
    md5 = hashlib.md5()  # noqa: S324 - fingerprinting, not crypto
    sha1 = hashlib.sha1()  # noqa: S324 - fingerprinting, not crypto
    sha256 = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
    return "\n".join(
        [
            f"=== Hashes: {p.name} ({p.stat().st_size} bytes) ===",
            f"  MD5:    {md5.hexdigest()}",
            f"  SHA-1:  {sha1.hexdigest()}",
            f"  SHA-256:{sha256.hexdigest()}",
        ]
    )


def compare_binaries(path_a: str, path_b: str) -> str:
    pa = Path(path_a)
    pb = Path(path_b)
    for p, name in ((pa, path_a), (pb, path_b)):
        if not p.exists():
            return f"[error] File not found: {name}"

    def _chunks(path: Path) -> list[bytes]:
        with path.open("rb") as f:
            return list(iter(lambda: f.read(4096), b""))

    chunks_a = _chunks(pa)
    chunks_b = _chunks(pb)
    size_a = sum(len(c) for c in chunks_a)
    size_b = sum(len(c) for c in chunks_b)
    common = min(len(chunks_a), len(chunks_b))
    matched: float = 0.0
    first_diff: int | None = None
    for i in range(common):
        if chunks_a[i] == chunks_b[i]:
            matched += 1
        else:
            matched += _partial_equal(chunks_a[i], chunks_b[i]) / 4096.0
            if first_diff is None:
                first_diff = i * 4096

    similarity = (matched / common * 100.0) if common else (100.0 if size_a == size_b else 0.0)
    lines = [f"=== Compare: {pa.name} vs {pb.name} ==="]
    lines.append(f"  Size A: {size_a} ({_format_size(size_a)})")
    lines.append(f"  Size B: {size_b} ({_format_size(size_b)})")
    lines.append(f"  Similarity: {similarity:.1f}% (by 4KB blocks)")
    if size_a == size_b and chunks_a == chunks_b:
        lines.append("  Result: IDENTICAL")
    else:
        lines.append(f"  Result: DIFFERENT (first difference at byte offset {first_diff if first_diff is not None else 0})")
    return "\n".join(lines)


def _partial_equal(a: bytes, b: bytes) -> int:
    return sum(1 for x, y in zip(a, b, strict=False) if x == y)

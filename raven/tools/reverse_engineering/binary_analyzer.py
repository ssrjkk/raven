from __future__ import annotations

import re
import struct
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
    raw = p.read_bytes()[:64]
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
        offset = 16 if info["bits"] == 32 else 16
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
            characteristics = struct.unpack("<H", raw[pe_offset + 22 : pe_offset + 24])[0]
            if characteristics & 0x2000:
                info["subsystem"] = "DLL"
            elif characteristics & 0x0002:
                info["subsystem"] = "EXE"

    elif raw[:4] == b"\xfe\xed\xfa\xce" or raw[:4] == b"\xce\xfa\xed\xfe":
        info["type"] = "Mach-O"
        info["architecture"] = "32-bit big-endian"
    elif raw[:4] == b"\xfe\xed\xfa\xcf" or raw[:4] == b"\xcf\xfa\xed\xfe":
        info["type"] = "Mach-O"
        info["architecture"] = "64-bit"
        if raw[:4] == b"\xcf\xfa\xed\xfe":
            info["endian"] = "little"

    elif raw[:8] == b"\xca\xfe\xba\xbe":
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


def _try_pyelftools(path: str) -> dict[str, Any] | None:
    import importlib.util

    if not importlib.util.find_spec("elftools"):
        return None
    try:
        from elftools.elf.elffile import ELFFile

        with open(path, "rb") as f:
            elf = ELFFile(f)
            sections = []
            for sec in elf.iter_sections():
                s = {"name": sec.name, "type": str(sec.header.sh_type), "size": sec.header.sh_size}
                try:
                    s["addr"] = hex(sec.header.sh_addr)
                except Exception as e:
                    logger.debug("Section addr extraction failed: {}", e)
                    s["addr"] = "0x0"
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


def _parse_elf_raw(raw: bytes, info: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    bits = info.get("bits", 64)
    endian = info.get("endian", "little")
    endian_fmt = "<" if endian == "little" else ">"

    if bits == 64:
        struct.unpack(endian_fmt + "Q", raw[32:40])[0]
        sh_off = struct.unpack(endian_fmt + "Q", raw[40:48])[0]
        ph_num = struct.unpack(endian_fmt + "H", raw[54:56])[0]
        sh_num = struct.unpack(endian_fmt + "H", raw[60:62])[0]
        struct.unpack(endian_fmt + "H", raw[54:56])[0] if False else 56
    else:
        struct.unpack(endian_fmt + "I", raw[28:32])[0]
        sh_off = struct.unpack(endian_fmt + "I", raw[32:36])[0]
        ph_num = struct.unpack(endian_fmt + "H", raw[44:46])[0]
        sh_num = struct.unpack(endian_fmt + "H", raw[48:50])[0]

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

    ft = file_type.get("type", "")
    if ft == "ELF":
        elf_info = _try_pyelftools(str(p))
        if elf_info:
            if "sections" in elf_info:
                lines.append(f"\n  Sections ({len(elf_info['sections'])}):")
                for s in elf_info["sections"][:30]:
                    lines.append(f"    {s['name']:20s} addr={s.get('addr', '?'):14s} size={s['size']}")
            if "symbols" in elf_info:
                lines.append(f"\n  Symbols ({len(elf_info['symbols'])}):")
                for s in elf_info["symbols"][:20]:
                    lines.append(f"    {s['value']:18s} {s['name']}")
        else:
            raw_info = _parse_elf_raw(raw, file_type)
            if "segment_count" in raw_info:
                lines.append(f"\n  Segments: {raw_info['segment_count']}")
                lines.append(f"  Sections: {raw_info['section_count']}")

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
    else:
        lines.append("\n  (detailed parsing requires pyelftools or pefile)")

    lines.append(f"\n  Entropy: {_calculate_entropy(raw):.3f}")
    lines.append(f"  Strings found: {_count_strings(raw)}")

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
            elif re.match(r"[a-zA-Z]:\\\\", s) or s.startswith("/") or s.startswith("./"):
                classified["paths"].append(s)
            elif re.match(r"^[A-Fa-f0-9]{32,64}$", s):
                classified["crypto"].append(s[:64])
            elif re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", s):
                classified["ip"].append(s)
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s) and 2 < len(s) < 60:
                classified["function_names"].append(s)
            elif s.startswith("HK") or s.startswith("HKEY"):
                classified["registry"].append(s)
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

    entropy = 0.0
    for x in range(256):
        p_x = data.count(x) / len(data)
        if p_x > 0:
            entropy += -p_x * log2(p_x)
    return entropy


def _count_strings(data: bytes) -> int:
    return len(re.findall(rb"[\x20-\x7e]{4,}", data))

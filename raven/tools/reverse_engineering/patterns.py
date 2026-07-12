from __future__ import annotations

import re
import struct
from pathlib import Path

from loguru import logger

PACKER_SIGNATURES: list[tuple[str, list[tuple[int, bytes]], str]] = [
    ("UPX", [(0, b"UPX!"), (0, b"UPX0")], "UPX packer detected"),
    ("UPX", [(0, b"UPX!"), (0, b"UPX1")], "UPX packer detected"),
    ("VMProtect", [(0, b"\x00\x00\x00\x00\x55\x8b\xec\x83\xe4\xf8")], "VMProtect entrypoint pattern"),
    ("Themida", [(0, b"\xeb\xfe")], "Themida anti-debug infinite loop"),
    ("ASPack", [(0x40, b"ASPack")], "ASPack detected"),
    ("Armadillo", [(0, b"\x55\x8b\xec\x6a\xff\x68")], "Armadillo protection pattern"),
    ("NSIS", [(0, b"NSIS")], "NSIS installer detected"),
    ("MPRESS", [(0, b"MPRESS")], "MPRESS packer detected"),
    ("Enigma", [(0, b"\x68\x01\x01\x01\x01\xff\x15")], "Enigma protector pattern"),
]


CRYPTO_CONSTANTS: list[tuple[str, bytes, str]] = [
    ("AES", b"\x63\x7c\x77\x7b\xf2\x6b\x6f\xc5", "AES S-box (first 8 bytes)"),
    ("AES", b"\x00\x04\x08\x0c\x10\x14\x18\x1c", "AES rcon (first 8 bytes)"),
    ("RC4", b"\x00\x01\x02\x03\x04\x05\x06\x07", "RC4 key schedule init"),
    ("MD5", b"\x01\x23\x45\x67\x89\xab\xcd\xef", "MD5 initial constants"),
    ("SHA256", b"\x6a\x09\xe6\x67\xbb\x67\xae\x85", "SHA256 K constants"),
    ("Blowfish", b"\x24\x30\x46\x6e\x6e\x86\xd2\x46", "Blowfish P-array"),
    ("XTA", b"\xe8\xa7\x3d\xf5\x67\xd2\xa3\x9b", "XTA cipher constants"),
    ("Base64", b"\x41\x42\x43\x44\x45\x46\x47\x48", "Base64 alphabet 'ABCDEFGH'"),
    ("CRC32", b"\xed\xb8\x83\x20", "CRC32 polynomial reversed"),
]


ANTI_DEBUG_PATTERNS: list[tuple[str, str, str]] = [
    (
        "ptrace",
        r"\xbe[\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10]\x00\x00\x00\xbf[\x01\x02]\x00\x00\x00",
        "ptrace(PT_TRACE_ME) anti-debug",
    ),
    ("IsDebuggerPresent", r"\x64\xa1\x30\x00\x00\x00", "IsDebuggerPresent (PEB->BeingDebugged)"),
    ("NtGlobalFlag", r"\x64\xa1[\x30\x18]\x00\x00\x00", "NtGlobalFlag check"),
    ("OutputDebugString", r"\xff\x15[\x00\x00\x00\x00\x00\x00\x00\x00]", "OutputDebugString anti-debug via exception"),
    ("TrapFlag", r"\x9c\x50\x81\x61\x00\x00\x00\x00\x00\x01\x00\x00", "TrapFlag (TF) manipulation"),
    ("TimingCheck", r"\x0f\x31", "RDTSC timing check (tick counter)"),
]

_SUSPICIOUS_API_PATTERNS: dict[str, list[str]] = {
    "process_injection": [
        "VirtualAllocEx",
        "WriteProcessMemory",
        "CreateRemoteThread",
        "NtCreateThreadEx",
        "RtlCreateUserThread",
        "QueueUserAPC",
        "SetThreadContext",
        "GetThreadContext",
        "ZwUnmapViewOfSection",
    ],
    "anti_debug_api": [
        "NtQueryInformationProcess",
        "CheckRemoteDebuggerPresent",
        "NtSetInformationThread",
        "HideThreadFromDebugger",
    ],
    "keylog_sniff": [
        "SetWindowsHookEx",
        "GetAsyncKeyState",
        "GetForegroundWindow",
        "GetWindowText",
        "GetClipboardData",
        "SetClipboardData",
        "GetKeyState",
        "GetKeyboardState",
    ],
    "persistence": [
        "RegSetValueEx",
        "RegCreateKeyEx",
        "CreateService",
        "OpenSCManager",
        "StartServiceCtrlDispatcher",
    ],
    "network": [
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
        "HttpOpenRequest",
        "URLDownloadToFile",
        "WinHttpOpen",
        "WinHttpConnect",
    ],
    "crypto": [
        "CryptEncrypt",
        "CryptDecrypt",
        "CryptDeriveKey",
        "CryptHashData",
        "CryptAcquireContext",
        "BCryptEncrypt",
        "BCryptDecrypt",
        "NCryptEncrypt",
        "NCryptDecrypt",
    ],
    "injection_bypass": [
        "NtOpenProcess",
        "NtAllocateVirtualMemory",
        "NtWriteVirtualMemory",
        "NtProtectVirtualMemory",
        "NtClose",
    ],
}


async def detect_patterns(path: str, patterns: str = "all") -> str:
    p = Path(path)
    if not p.exists():
        return f"[error] File not found: {path}"
    raw = p.read_bytes()

    requested = set(patterns.lower().split(","))

    lines = [f"=== Pattern Detection: {p.name} ==="]
    lines.append(f"  File size: {len(raw)} bytes\n")

    if "all" in requested or "packers" in requested:
        lines.extend(_scan_packers(raw))

    if "all" in requested or "crypto" in requested:
        lines.extend(_scan_crypto(raw))

    if "all" in requested or "anti_debug" in requested:
        lines.extend(_scan_anti_debug(raw))

    if "all" in requested or "vulns" in requested:
        lines.extend(_scan_vulns(raw))

    if "all" in requested or "apis" in requested:
        lines.extend(_scan_apis(raw))

    found = len(lines) - 3
    if found == 0:
        lines.append("  No suspicious patterns detected.")
    lines.append(f"\n  Total findings: {found}")

    return "\n".join(lines)


def _scan_packers(raw: bytes) -> list[str]:
    results: list[str] = []
    results.append("--- Packers ---")
    packer_found = False
    for _name, sig_entries, desc in PACKER_SIGNATURES:
        for sig_offset, sig_bytes in sig_entries:
            if isinstance(sig_bytes, str):
                sig_bytes = sig_bytes.encode()
            end = sig_offset + len(sig_bytes)
            if len(raw) > end and raw[sig_offset:end] == sig_bytes:
                results.append(f"  [PACKER] {desc}")
                packer_found = True
                break
    if not packer_found:
        results.append("  No known packer signatures found")
    return results


def _scan_crypto(raw: bytes) -> list[str]:
    results: list[str] = []
    results.append("\n--- Crypto Constants ---")
    crypto_found = False
    for _name, sig, desc in CRYPTO_CONSTANTS:
        if sig in raw:
            results.append(f"  [CRYPTO] {desc}")
            crypto_found = True
    if not crypto_found:
        results.append("  No known crypto constants found")
    return results


def _scan_anti_debug(raw: bytes) -> list[str]:
    results: list[str] = []
    results.append("\n--- Anti-Debug ---")
    ad_found = False
    for _name, pattern, desc in ANTI_DEBUG_PATTERNS:
        try:
            if re.search(pattern.encode(), raw):
                results.append(f"  [ANTI-DEBUG] {desc}")
                ad_found = True
        except re.error:
            pass
    if not ad_found:
        results.append("  No anti-debug patterns found")
    return results


def _scan_vulns(raw: bytes) -> list[str]:
    results: list[str] = []
    results.append("\n--- Vulnerabilities (syntactic hints) ---")
    findings = 0

    dangerous_functions = [
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

    for func_bytes, desc in dangerous_functions:
        if func_bytes in raw:
            results.append(f"  [VULN] {desc}")
            findings += 1

    if findings == 0:
        results.append("  No obvious vulnerability indicators")
    return results


def _scan_apis(raw: bytes) -> list[str]:
    results: list[str] = []
    results.append("\n--- Suspicious API Usage ---")
    findings = 0

    try:
        imports = _extract_imports(raw)
        if not imports:
            results.append("  (no import table or import parsing disabled)")
            return results

        for category, apis in _SUSPICIOUS_API_PATTERNS.items():
            found = [api for api in apis if api in imports]
            if found:
                results.append(f"  [{category}] ({len(found)}): {', '.join(found[:10])}")
                findings += len(found)

        if findings == 0:
            results.append("  No suspicious APIs found")
    except Exception as e:
        results.append(f"  API scan error: {e}")

    return results


def _extract_imports(raw: bytes) -> set[str]:
    imports: set[str] = set()

    if raw[:2] == b"MZ":
        try:
            pe_off = struct.unpack("<I", raw[0x3C:0x40])[0]
            num_sections = struct.unpack("<H", raw[pe_off + 6 : pe_off + 8])[0]
            sect_off = pe_off + 248
            import_dir_rva = 0
            opt_magic = struct.unpack("<H", raw[pe_off + 24 : pe_off + 26])[0]
            if opt_magic == 0x10B:
                import_dir_rva = struct.unpack("<I", raw[pe_off + 104 : pe_off + 108])[0]
                struct.unpack("<I", raw[pe_off + 108 : pe_off + 112])[0]
            elif opt_magic == 0x20B:
                import_dir_rva = struct.unpack("<I", raw[pe_off + 120 : pe_off + 124])[0]
                struct.unpack("<I", raw[pe_off + 124 : pe_off + 128])[0]

            if import_dir_rva:
                import_table_raw = _rva_to_raw(raw, import_dir_rva, num_sections, sect_off, pe_off)
                if import_table_raw:
                    offset = import_table_raw
                    while offset + 20 <= len(raw):
                        ilt = struct.unpack("<I", raw[offset : offset + 4])[0]
                        name_rva = struct.unpack("<I", raw[offset + 12 : offset + 16])[0]
                        if ilt == 0 and name_rva == 0:
                            break
                        if name_rva:
                            name_raw = _rva_to_raw(raw, name_rva, num_sections, sect_off, pe_off)
                            if name_raw and name_raw + 2 < len(raw):
                                name_bytes = raw[name_raw + 2 : name_raw + 260]
                                end = name_bytes.find(b"\x00")
                                if end > 0:
                                    imports.add(name_bytes[:end].decode("ascii", errors="replace"))
                        offset += 20
        except Exception as e:
            logger.debug("PE import parsing failed: {}", e)

    elif raw[:4] == b"\x7fELF" or raw[:4] == b"\xfe\xed\xfa":
        text_strings = re.findall(rb"[\x20-\x7e]{4,}", raw)
        known_apis = set()
        for cat in _SUSPICIOUS_API_PATTERNS.values():
            known_apis.update(cat)
        for s in text_strings:
            dec = s.decode("ascii", errors="replace")
            if dec in known_apis:
                imports.add(dec)

    return imports


def _rva_to_raw(raw: bytes, rva: int, num_sections: int, sect_off: int, pe_off: int) -> int | None:
    for i in range(min(num_sections, 100)):
        off = sect_off + i * 40
        vaddr = struct.unpack("<I", raw[off + 12 : off + 16])[0]
        vsize = struct.unpack("<I", raw[off + 8 : off + 12])[0]
        raw_ptr = struct.unpack("<I", raw[off + 20 : off + 24])[0]
        raw_size = struct.unpack("<I", raw[off + 16 : off + 20])[0]

        if vaddr <= rva < vaddr + max(vsize, raw_size):
            return int(raw_ptr + (rva - vaddr))
    return None

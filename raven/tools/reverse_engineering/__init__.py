from __future__ import annotations

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.tools.reverse_engineering.binary_analyzer import (
    analyze_binary,
    compare_binaries,
    extract_strings,
    get_file_type,
    hash_binary,
    hexdump,
)
from raven.tools.reverse_engineering.disassembler import disassemble_bytes, disassemble_file
from raven.tools.reverse_engineering.patterns import detect_patterns, detect_toolchain

__all__ = [
    "analyze_binary",
    "compare_binaries",
    "detect_patterns",
    "detect_toolchain",
    "disassemble_bytes",
    "disassemble_file",
    "extract_strings",
    "get_file_type",
    "hash_binary",
    "hexdump",
    "register_re_tools",
]


def register_re_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="analyze_binary",
            description="Analyze a binary file: ELF/PE/MachO headers, sections, imports, exports, architecture",
            parameters={
                "path": {"type": "string", "description": "Path to binary file", "required": True},
            },
            handler=analyze_binary,
            category="reverse_engineering",
            timeout=60,
        )
    )
    registry.register(
        ToolSpec(
            name="hexdump",
            description="Hex dump a section of a binary file",
            parameters={
                "path": {"type": "string", "description": "Path to binary file", "required": True},
                "offset": {
                    "type": "integer",
                    "description": "Byte offset to start dump from (default: 0)",
                    "required": False,
                },
                "length": {
                    "type": "integer",
                    "description": "Number of bytes to dump (default: 256)",
                    "required": False,
                },
            },
            handler=hexdump,
            category="reverse_engineering",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="hash_binary",
            description="Compute MD5/SHA-1/SHA-256 hashes of a binary file (fingerprinting)",
            parameters={
                "path": {"type": "string", "description": "Path to binary file", "required": True},
            },
            handler=hash_binary,
            category="reverse_engineering",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="compare_binaries",
            description="Compare two binary files block-by-block and report similarity",
            parameters={
                "path_a": {"type": "string", "description": "First file", "required": True},
                "path_b": {"type": "string", "description": "Second file", "required": True},
            },
            handler=compare_binaries,
            category="reverse_engineering",
            timeout=60,
        )
    )
    registry.register(
        ToolSpec(
            name="detect_toolchain",
            description="Detect compiler/runtime toolchain in a binary (Go, Rust, .NET, PyInstaller, Electron, MSVC, MinGW)",
            parameters={
                "path": {"type": "string", "description": "Path to binary file", "required": True},
            },
            handler=detect_toolchain,
            category="reverse_engineering",
            timeout=60,
        )
    )
    registry.register(
        ToolSpec(
            name="disassemble",
            description="Disassemble a binary file at a given address/symbol or whole section",
            parameters={
                "path": {"type": "string", "description": "Path to binary file", "required": True},
                "symbol": {
                    "type": "string",
                    "description": "Function/symbol name or hex address (e.g. 0x401000)",
                    "required": False,
                },
                "bytes": {
                    "type": "integer",
                    "description": "Number of bytes to disassemble (default: entire .text)",
                    "required": False,
                },
                "arch": {
                    "type": "string",
                    "description": "Architecture: auto/x86/x64/arm/arm64/mips/riscv (default: auto-detect)",
                    "required": False,
                },
            },
            handler=disassemble_file,
            category="reverse_engineering",
            timeout=120,
        )
    )
    registry.register(
        ToolSpec(
            name="extract_strings",
            description="Extract and classify ASCII/Unicode strings from a binary file",
            parameters={
                "path": {"type": "string", "description": "Path to binary file", "required": True},
                "min_length": {
                    "type": "integer",
                    "description": "Minimum string length (default: 4)",
                    "required": False,
                },
                "classify": {
                    "type": "boolean",
                    "description": "Classify strings by type (URL, path, crypto, etc.)",
                    "required": False,
                },
            },
            handler=extract_strings,
            category="reverse_engineering",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="detect_patterns",
            description="Detect suspicious patterns in binary: packers, crypto constants, anti-debug, common vulns",
            parameters={
                "path": {"type": "string", "description": "Path to binary file", "required": True},
                "patterns": {
                    "type": "string",
                    "description": "Comma-separated: packers,crypto,anti_debug,vulns,all (default: all)",
                    "required": False,
                },
            },
            handler=detect_patterns,
            category="reverse_engineering",
            timeout=120,
        )
    )

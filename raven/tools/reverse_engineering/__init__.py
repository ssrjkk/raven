from __future__ import annotations

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.tools.reverse_engineering.binary_analyzer import (
    analyze_binary,
    extract_strings,
    get_file_type,
)
from raven.tools.reverse_engineering.disassembler import disassemble_bytes, disassemble_file
from raven.tools.reverse_engineering.patterns import detect_patterns

__all__ = [
    "analyze_binary",
    "detect_patterns",
    "disassemble_bytes",
    "disassemble_file",
    "extract_strings",
    "get_file_type",
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
                    "description": "Architecture: auto/x86/x64/arm/arm64/mips (default: auto-detect)",
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

from __future__ import annotations

from pathlib import Path

from loguru import logger

from raven.core.coder.analyzer import CodeAnalyzer
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


def analyze_code(path: str, detail: str = "summary") -> str:
    """Analyze source code and return structured analysis.

    Args:
        path: File or directory path to analyze
        detail: Level of detail — "summary", "symbols", "calls", or "full"
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"Path not found: {p}"
    try:
        root = p.parent if p.is_file() else p
        analyzer = CodeAnalyzer(str(root))
        if p.is_file():
            result = analyzer.explain_file(p)
            if detail == "summary":
                return result.summary
            if detail == "symbols":
                lines: list[str] = [result.summary, ""]
                for sym in result.symbols:
                    ctx = f" in {sym.parent}" if sym.parent else ""
                    doc = f" — {sym.docstring[:80]}" if sym.docstring else ""
                    lines.append(f"  {sym.name} ({sym.kind}{ctx}) L{sym.line}{doc}")
                return "\n".join(lines)
            if detail == "calls":
                lines = [result.summary, "", "Call graph:"]
                for caller, callee, line in sorted(result.call_graph, key=lambda x: x[2]):
                    lines.append(f"  {caller} → {callee}  (L{line})")
                return "\n".join(lines)
            return analyzer.format_explain(result, show_all=True)
        results = analyzer.analyze(p)
        return analyzer.format_analysis(results)
    except Exception as e:
        logger.exception("analyze_code failed")
        return f"Analysis failed: {e}"


def explain_code(path: str, function: str = "") -> str:
    """Explain what a piece of code does line by line.

    Args:
        path: File path to explain
        function: Optional function name to trace execution of
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"File not found: {p}"
    try:
        analyzer = CodeAnalyzer(str(p.parent))
        if function:
            return analyzer.trace_function(p, function)
        result = analyzer.explain_file(p)
        lines: list[str] = [result.summary, ""]
        for al in result.annotated_lines:
            if not al.explanation and not al.origin_info:
                continue
            tag = ""
            if al.is_definition:
                tag = "[DEF]"
            elif al.is_import:
                tag = "[IMP]"
            elif al.is_call:
                tag = "[CALL]"
            lines.append(f"  L{al.number:4d} {tag} {al.code.rstrip()[:60]}")
            if al.explanation:
                lines.append(f"          └─ {al.explanation}")
            if al.origin_info:
                lines.append(f"          └─ {al.origin_info}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("explain_code failed")
        return f"Explanation failed: {e}"


def register_code_analysis_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="analyze_code",
            description="Analyze source code: show structure, symbols, call graph, dependencies",
            parameters={
                "path": {"type": "string", "description": "File or directory path", "required": True},
                "detail": {
                    "type": "string",
                    "description": "Detail level: summary|symbols|calls|full",
                    "enum": ["summary", "symbols", "calls", "full"],
                    "required": False,
                },
            },
            handler=analyze_code,
            category="coding",
        )
    )
    registry.register(
        ToolSpec(
            name="explain_code",
            description="Explain code line by line with annotations showing what each part does and where symbols come from",
            parameters={
                "path": {"type": "string", "description": "File path", "required": True},
                "function": {
                    "type": "string",
                    "description": "Optional function name to trace",
                    "required": False,
                },
            },
            handler=explain_code,
            category="coding",
        )
    )

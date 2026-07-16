from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from raven.core.config import settings

console = Console()


def _run_async(coro):
    return asyncio.run(coro)


@click.group(name="code")
def code_group():
    """Coding assistant — index, review, sessions"""


@code_group.command("index")
@click.argument("path", default=".", required=False)
@click.option("--max-files", default=2000, type=int, help="Max files to index")
def code_index(path: str, max_files: int):
    """Index a codebase for context-aware assistance"""
    from raven.core.coder.indexer import CodeIndexer

    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        console.print(f"[red]Not a directory: {p}[/red]")
        return
    with console.status("[bold]Indexing...", spinner="dots"):
        indexer = CodeIndexer(str(p))
        indexer.index(max_files=max_files)
    summary = indexer.summary()
    console.print(f"[green]Indexed {summary['files']} files[/green]")
    for lang, count in summary.get("languages", {}).items():
        console.print(f"  {lang}: {count} files")


@code_group.command("search")
@click.argument("query")
@click.argument("path", default=".", required=False)
def code_search(query: str, path: str):
    """Search indexed codebase for symbols"""
    from raven.core.coder.indexer import CodeIndexer

    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        p = Path.cwd()
    with console.status("[bold]Searching...", spinner="dots"):
        indexer = CodeIndexer(str(p))
        indexer.index(max_files=2000)
        results = indexer.search(query)

    if not results:
        console.print("[yellow]No results found[/yellow]")
        return
    table = Table(title=f"Search: {query}")
    table.add_column("File", style="cyan")
    table.add_column("Language", style="blue")
    table.add_column("Symbols", style="green")
    for f in results[:20]:
        syms = ", ".join(s.name for s in f.symbols[:5])
        table.add_row(f.path, f.language, syms)
    console.print(table)


@code_group.command("review")
@click.argument("path")
@click.option("--language", default="", help="Programming language")
def code_review(path: str, language: str):
    """Review a file for issues"""
    from raven.core.coder.review import CodeReviewer

    p = Path(path).expanduser().resolve()
    if not p.is_file():
        console.print(f"[red]File not found: {p}[/red]")
        return
    content = p.read_text(encoding="utf-8", errors="replace")
    ext = p.suffix
    lang_map = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go", ".rs": "rust", ".java": "java"}
    lang = language or lang_map.get(ext, "")

    reviewer = CodeReviewer()
    comments = asyncio.run(reviewer.review_file(str(p), content, lang))

    if not comments:
        console.print("[green]No issues found![/green]")
        return

    table = Table(title=f"Review: {p.name}")
    table.add_column("Line", style="cyan")
    table.add_column("Severity")
    table.add_column("Issue", style="white")
    table.add_column("Suggestion", style="dim")
    for c in comments:
        severity_colors = {"critical": "red", "warning": "yellow", "suggestion": "blue", "praise": "green"}
        table.add_row(
            str(c.line),
            f"[{severity_colors.get(c.severity.value, 'white')}]{c.severity.value}[/]",
            c.message,
            c.suggestion,
        )
    console.print(table)


@code_group.command("start")
@click.argument("goal")
@click.option("--project", default=".", help="Project path")
@click.option("--user", default="cli", help="User ID")
def code_start(goal: str, project: str, user: str):
    """Start a coding session"""
    async def _inner():
        from raven.core.coder.models import CodingSession
        from raven.core.coder.session import CodingSessionManager

        p = Path(project).expanduser().resolve()
        session = CodingSession(user_id=user, goal=goal, project_path=str(p))
        mgr = CodingSessionManager(settings.resolved_db_path)
        await mgr.create_session(session)
        console.print(f"[green]Coding session started: {session.id[:8]}[/green]")
        console.print(f"  Goal: {goal}")
        console.print(f"  Project: {p}")
        console.print(f"  [dim]Run 'raven code status {session.id[:8]}' to check[/dim]")
    _run_async(_inner())


@code_group.command("status")
@click.argument("session_id")
def code_status(session_id: str):
    """Show coding session status"""
    async def _inner():
        from raven.core.coder.session import CodingSessionManager

        mgr = CodingSessionManager(settings.resolved_db_path)
        session = await mgr.get_session(session_id)
        if not session:
            console.print(f"[red]Session not found: {session_id}[/red]")
            return
        console.print(
            Panel.fit(
                f"[bold]Coding Session: {session.id}[/bold]\n"
                f"[cyan]Goal:[/cyan] {session.goal}\n"
                f"[cyan]Project:[/cyan] {session.project_path}\n"
                f"[cyan]Status:[/cyan] {session.status.value}\n"
                f"[cyan]Files:[/cyan] {len(session.files)}\n"
                f"[cyan]Messages:[/cyan] {len(session.history)}"
            )
        )
    _run_async(_inner())


@code_group.command("end")
@click.argument("session_id")
def code_end(session_id: str):
    """End a coding session"""
    async def _inner():
        from raven.core.coder.models import SessionStatus
        from raven.core.coder.session import CodingSessionManager

        mgr = CodingSessionManager(settings.resolved_db_path)
        session = await mgr.get_session(session_id)
        if not session:
            console.print(f"[red]Session not found: {session_id}[/red]")
            return
        session.status = SessionStatus.COMPLETED
        await mgr.update_session(session)
        console.print(f"[green]Session {session_id[:8]} ended[/green]")
    _run_async(_inner())


@code_group.command("analyze")
@click.argument("path", default=".", required=False)
@click.option("--all", "show_all", is_flag=True, help="Show all lines including unannotated")
def code_analyze(path: str, show_all: bool):
    """Analyze codebase structure — dependencies, call graph, symbols"""
    from raven.core.coder.analyzer import CodeAnalyzer

    p = Path(path).expanduser().resolve()
    analyzer = CodeAnalyzer(str(p.parent if p.is_file() else p))
    if p.is_file():
        result = analyzer.explain_file(p)
        console.print(result.summary)
        if result.symbols:
            console.print(Panel.fit(
                "\n".join(f"  {s.name} ({s.kind}, line {s.line})" + (f" — {s.docstring[:50]}" if s.docstring else "")
                          for s in result.symbols),
                title="Symbols",
            ))
        if result.call_graph:
            table = Table(title="Call Graph")
            table.add_column("Caller", style="cyan")
            table.add_column("Callee", style="green")
            table.add_column("Line", style="dim")
            for caller, callee, line in sorted(result.call_graph, key=lambda x: x[2]):
                table.add_row(caller, callee, str(line))
            console.print(table)
    else:
        results = analyzer.analyze(p)
        console.print(analyzer.format_analysis(results))


@code_group.command("explain")
@click.argument("path")
@click.option("--all", "show_all", is_flag=True, help="Show every line")
@click.option("--function", "-f", "func_name", default="", help="Trace a specific function")
def code_explain(path: str, show_all: bool, func_name: str):
    """Explain code line-by-line with annotations and origin info"""
    from raven.core.coder.analyzer import CodeAnalyzer

    p = Path(path).expanduser().resolve()
    if not p.exists():
        console.print(f"[red]File not found: {p}[/red]")
        return
    analyzer = CodeAnalyzer(str(p.parent))
    if func_name:
        trace = analyzer.trace_function(p, func_name)
        console.print(trace)
        return
    result = analyzer.explain_file(p)
    console.print(result.summary)
    if not result.annotated_lines:
        return
    table = Table(title=f"Annotations: {p.name}", show_lines=True)
    table.add_column("Line", style="dim", width=4)
    table.add_column("Code", style="white", width=60)
    table.add_column("Explanation / Origin", style="yellow", width=50)
    for al in result.annotated_lines:
        if not show_all and not al.explanation and not al.origin_info:
            continue
        label = ""
        if al.is_definition:
            label = "[bold]▸[/bold] "
        elif al.is_import:
            label = "[blue]→[/blue] "
        elif al.is_call:
            label = "[green]↪[/green] "
        detail = al.explanation
        if al.origin_info:
            detail = (detail + "; " if detail else "") + al.origin_info
        code_display = al.code.rstrip()[:58]
        table.add_row(str(al.number), f"{label}{code_display}", detail[:48] if detail else "")
    console.print(table)

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any

import click
from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.lsp import enrich_context
from ravencode.runtime.multisession import get_session_manager

console = Console()

_STYLE_USER = "bold green"
_STYLE_AGENT = "bold blue"
_STYLE_TOOL = "bold yellow"
_STYLE_ERROR = "bold red"
_STYLE_MUTED = "dim"
_STYLE_SYSTEM = "bold magenta"


class TUIEventEmitter(EventEmitter):
    def __init__(self, live: Live | None = None) -> None:
        super().__init__()
        self._live = live
        self._current_step = 0

    def set_live(self, live: Live) -> None:
        self._live = live

    async def emit(self, event: AgentEvent) -> None:
        if event.type == "step_start":
            self._current_step = event.data.get("step", 0)
        elif event.type == "tool_call":
            name = event.data.get("name", "?")
            args = event.data.get("args", {})
            args_str = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
            console.print(f"  {_STYLE_TOOL}⚡ {name}({args_str})")
        elif event.type == "tool_result":
            result = event.data.get("result", "")
            first_line = result.split("\n")[0][:120]
            if first_line:
                console.print(f"  {_STYLE_MUTED}→ {first_line}")
        await super().emit(event)


def _print_welcome() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold]Raven Code Agent[/bold]\n"
        "Type your coding task, or use commands:\n"
        "  /multisession  — list parallel sessions\n"
        "  /plan          — plan-only mode (read-only)\n"
        "  /safe          — safe mode (confirm dangerous)\n"
        "  /fast          — fast mode (no confirm, no preview)\n"
        "  /exit  /quit   — exit\n"
        "  Ctrl+C — abort current request\n"
        "  Ctrl+D — exit",
        border_style="cyan",
    ))
    console.print()


def _build_system_prompt(project_root: Path | None, lsp_context: str | None = None) -> str:
    base = (
        "You are Raven, an AI coding assistant running in the terminal.\n"
        "You have tools for reading, writing, editing files, running commands, searching code, "
        "managing git, web search, and delegating subtasks.\n\n"
        "Rules:\n"
        "1. Always read before editing.\n"
        "2. Show diffs before applying changes.\n"
        "3. Verify changes with tests or lint when possible.\n"
        "4. When the user provides a complex task, break it into steps.\n"
        "5. If you need more information, ask.\n"
        "6. If a tool fails, try an alternative approach.\n"
    )

    if project_root:
        base += f"\nProject root: {project_root.resolve()}\n"

    if lsp_context:
        base += f"\n--- Project Context ---\n{lsp_context}\n"

    return base


async def _run_interactive(
    agent: ReActAgent,
    project_root: Path | None,
) -> None:
    ee = TUIEventEmitter()
    agent.config.event_emitter = ee

    while True:
        try:
            line = await asyncio.to_thread(_read_input)
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print("[yellow]Bye![/yellow]")
            break

        if line is None:
            continue

        if line.strip() in ("/exit", "/quit", ":q"):
            console.print("[yellow]Bye![/yellow]")
            break

        if line.strip() == "/multisession":
            _show_multisessions()
            continue

        if line.strip() == "/plan":
            if agent.config.plan_mode:
                console.print("[yellow]Already in plan mode[/yellow]")
            else:
                agent.config.plan_mode = True
                agent.config.confirm_dangerous = False
                agent.config.diff_preview = False
                agent.config.proactive_scan = True
                console.print("[green]Switched to plan mode (read-only)[/green]")
            continue

        if line.strip() == "/safe":
            agent.config.plan_mode = False
            agent.config.confirm_dangerous = True
            agent.config.diff_preview = True
            console.print("[green]Switched to safe mode (confirm dangerous ops)[/green]")
            continue

        if line.strip() == "/fast":
            agent.config.plan_mode = False
            agent.config.confirm_dangerous = False
            agent.config.diff_preview = False
            console.print("[green]Switched to fast mode[/green]")
            continue

        if line.strip() == "/enrich":
            console.print("[dim]Enriching project context via LSP...[/dim]")
            ctx = await enrich_context(str(project_root) if project_root else None)
            if ctx and not ctx.startswith("("):
                agent.conversation.add_user_message(f"[LSP context]\n{ctx}")
                console.print("[green]Project context enriched[/green]")
            else:
                console.print(f"[yellow]{ctx}[/yellow]")
            continue

        if line.strip().startswith("/session "):
            parts = shlex.split(line.strip())
            if len(parts) >= 2:
                _switch_session(parts[1], agent)
            else:
                console.print("[yellow]Usage: /session <session-id>[/yellow]")
            continue

        if line.strip().startswith("/"):
            console.print(f"[yellow]Unknown command: {line.strip()}[/yellow]")
            continue

        console.print(Rule(style="dim"))
        console.print(f"{_STYLE_USER}You: {line}")

        try:
            result = await agent.run(line)
            if result:
                console.print(f"\n{_STYLE_AGENT}{result}")
        except asyncio.CancelledError:
            console.print("\n[yellow]Aborted[/yellow]")
        except Exception as exc:
            console.print(f"\n{_STYLE_ERROR}Error: {exc}")


def _read_input() -> str | None:
    try:
        line = input(f"\n{_STYLE_MUTED}raven> {_STYLE_SYSTEM}")
        return line
    except EOFError:
        raise
    except KeyboardInterrupt:
        raise


def _show_multisessions() -> None:
    mgr = get_session_manager()
    sessions = mgr.sessions
    if not sessions:
        console.print("[yellow]No parallel sessions[/yellow]")
        console.print("[dim]Use /session <name> <task> to start one[/dim]")
        return
    table = Table(title="Parallel Sessions")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Status", style="green")
    table.add_column("Messages", style="blue")
    for s in sessions:
        table.add_row(s.id[:8], s.name, s.status, str(s.message_count))
    console.print(table)


def _switch_session(session_id: str, current_agent: ReActAgent) -> None:
    mgr = get_session_manager()
    session = asyncio.run_coroutine_threadsafe(mgr.get(session_id), asyncio.get_event_loop()).result()
    if session:
        console.print(f"[green]Switched to session {session_id[:8]}[/green]")
    else:
        console.print(f"[yellow]Session not found: {session_id}[/yellow]")


async def _start_parallel_session(
    task: str,
    system_prompt: str | None = None,
    name: str = "",
) -> None:
    mgr = get_session_manager()
    session = await mgr.create(
        name=name,
        system_prompt=system_prompt,
        max_steps=50,
        confirm_dangerous=False,
    )
    console.print(f"[dim]Parallel session {session.id[:8]} started...[/dim]")
    result = await session.run(task)
    console.print(f"[bold]Result:[/bold] {result[:2000]}")
    await mgr.remove(session.id)


@click.command()
@click.argument("task", required=False, default="")
@click.option("--project", "-p", default=None, help="Project root directory")
@click.option("--agent", default="raven", help="Agent type name")
@click.option("--max-steps", default=50, type=int, help="Max agent steps")
@click.option("--safe", is_flag=True, help="Safe mode (confirm dangerous operations)")
@click.option("--plan", is_flag=True, help="Plan-only mode (read-only)")
@click.option("--model", default=None, help="LLM model override")
@click.option("--parallel", "-P", default=None, help="Start a parallel session with this task")
def code(
    task: str,
    project: str | None,
    agent: str,
    max_steps: int,
    safe: bool,
    plan: bool,
    model: str | None,
    parallel: str | None,
) -> None:
    """Interactive coding agent — like opencode in the terminal"""
    if parallel:
        asyncio.run(_start_parallel_session(parallel, name=task or "parallel"))
        return

    project_root = Path(project).resolve() if project else Path.cwd().resolve()
    if not project_root.is_dir():
        console.print(f"[red]Project directory not found: {project_root}[/red]")
        raise SystemExit(1)

    lsp_context = ""
    try:
        lsp_context = asyncio.run(enrich_context(str(project_root)))
    except Exception as exc:
        logger.debug("LSP enrichment failed: {}", exc)

    sys_prompt = _build_system_prompt(project_root, lsp_context)
    conv = Conversation(system_prompt=sys_prompt)

    config_kwargs: dict[str, Any] = dict(
        max_steps=max_steps,
        confirm_dangerous=safe,
        diff_preview=True,
        proactive_scan=True,
        auto_format=True,
    )
    if plan:
        config_kwargs["plan_mode"] = True
        config_kwargs["confirm_dangerous"] = False
        config_kwargs["diff_preview"] = False
    if model:
        config_kwargs["llm_timeout"] = 120

    cfg = AgentConfig(**config_kwargs)
    agent_obj = ReActAgent(config=cfg, conversation=conv, name=agent)

    _print_welcome()

    if lsp_context and not lsp_context.startswith("("):
        lines = lsp_context.split("\n")
        summary = lines[:6]
        console.print("[dim]LSP context loaded:[/dim]")
        for s in summary:
            console.print(f"  {_STYLE_MUTED}{s}")

    if task:
        console.print(f"\n{_STYLE_USER}Task: {task}")
        try:
            result = asyncio.run(agent_obj.run(task))
            if result:
                console.print(f"\n{_STYLE_AGENT}{result}")
        except Exception as exc:
            console.print(f"\n{_STYLE_ERROR}Error: {exc}")

    asyncio.run(_run_interactive(agent_obj, project_root))

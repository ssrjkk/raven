from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from ravencode.agents.custom_agents import get_custom_agents
from ravencode.agents.orchestrator import AgentResult, AgentType, Orchestrator
from ravencode.runtime.agent_core import AgentConfig, EventEmitter, ReActAgent
from ravencode.runtime.commands import CustomCommand, discover_commands
from ravencode.runtime.question import set_question_callback, stdin_question_callback

console = Console()


async def run_streaming_agent(prompt: str, config: AgentConfig) -> str:
    """Run an agent with live token streaming and tool-activity hints.

    Tokens print as they arrive; tool calls appear as dim inline lines. If
    the backend cannot stream, the final answer is shown in a panel instead.
    Mutates ``config``: wires the emitter and enables token streaming.
    """
    emitter = EventEmitter()
    streamed = 0

    async def on_token(ev: object) -> None:
        nonlocal streamed
        data = getattr(ev, "data", {})
        text = str(data.get("content", ""))
        streamed += len(text)
        console.print(text, end="", markup=False, highlight=False, soft_wrap=True)

    async def on_tool_call(ev: object) -> None:
        data = getattr(ev, "data", {})
        args = json.dumps(data.get("args", {}), ensure_ascii=False)
        console.print(f"\n[dim]> {data.get('name', '?')} {args[:120]}[/dim]")

    emitter.on("token", on_token)
    emitter.on("tool_call", on_tool_call)

    config.event_emitter = emitter
    config.stream_tokens = True
    config.priority = "high"  # a human is watching this run
    agent = ReActAgent(config=config)
    result = await agent.run(prompt)
    if streamed:
        console.print()
        console.print(f"[dim]done: {len(result)} chars[/dim]")
        return result
    console.print(Panel(Markdown(result), title="[bold blue]raven[/bold blue]", border_style="blue"))
    return result


def print_header() -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]RavenCode[/bold cyan] — AI Engineering Assistant",
            border_style="cyan",
        )
    )
    console.print()


def print_help() -> None:
    table = Table(title="Commands", box=None)
    table.add_column("Command", style="green")
    table.add_column("Description", style="white")
    table.add_row("/ask <prompt>", "Ask the autonomous agent a question")
    table.add_row("/plan <task>", "Create a plan for a task")
    table.add_row("/code <task>", "Execute a coding task")
    table.add_row("/debug <task>", "Debug an issue")
    table.add_row("/agent <name> <task>", "Use a custom agent by name")
    table.add_row("/undo", "Undo last file change")
    table.add_row("/redo", "Redo last undone change")
    table.add_row("/checkpoint save <desc>", "Save workspace snapshot")
    table.add_row("/checkpoint list", "List saved checkpoints")
    table.add_row("/checkpoint restore <id>", "Restore a checkpoint")
    table.add_row("/mcp", "Start MCP server mode")
    table.add_row("/history", "Show conversation history")
    table.add_row("/save [path]", "Save current session state to JSON file")
    table.add_row("/load [path]", "Load session state from JSON file")
    table.add_row("/help", "Show this help")
    table.add_row("/exit", "Exit")

    custom = discover_commands()
    if custom:
        table.add_section()
        table.add_row("[bold]Custom Commands[/bold]", "")
        for name, cmd in sorted(custom.items()):
            table.add_row(f"/{name}", cmd.description)
    console.print(table)


async def run_agent(task: str, agent_type: AgentType = AgentType.AUTONOMOUS) -> None:
    AgentConfig.safe()
    orch = Orchestrator()
    with console.status(f"[yellow]{agent_type.value} agent working...[/yellow]"):
        result: AgentResult = await orch.dispatch(task, agent_type)
    if result.success:
        text = str(result.data.get("result") or result.data.get("plan") or result.data.get("code_result") or "")
        console.print(Panel(Markdown(text), title=f"[bold green]{result.agent} ✓[/bold green]", border_style="green"))
    else:
        console.print(
            Panel(f"[red]{result.error}[/red]", title=f"[bold red]{result.agent} ✗[/bold red]", border_style="red")
        )


async def run_custom_command(cmd: CustomCommand, args: str) -> None:
    prompt = cmd.render_prompt(args)
    if cmd.subtask:
        from ravencode.agents.orchestrator import Orchestrator

        orch = Orchestrator()
        with console.status(f"[yellow]running {cmd.name}...[/yellow]"):
            result = await orch.delegate(prompt)
        console.print(Panel(Markdown(result), title=f"[bold]{cmd.name}[/bold]", border_style="blue"))
    elif cmd.agent:
        agent_type = (
            AgentType(cmd.agent.upper()) if cmd.agent.upper() in AgentType.__members__ else AgentType.AUTONOMOUS
        )
        await run_agent(prompt, agent_type)
    else:
        await run_streaming_agent(prompt, AgentConfig.safe())


async def main_loop() -> None:
    set_question_callback(stdin_question_callback)
    custom_commands = discover_commands()
    print_header()
    print_help()

    while True:
        try:
            raw = Prompt.ask("[bold cyan]raven[/bold cyan]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]bye![/yellow]")
            break

        cmd = raw.strip()
        if not cmd:
            continue

        if cmd == "/exit":
            break

        if cmd == "/help":
            print_help()
            continue

        if cmd == "/history":
            console.print("[yellow]history available via MemoryStore keys()[/yellow]")
            continue

        if cmd == "/undo":
            from ravencode.runtime.undo import undo_last

            result = await undo_last()
            console.print(result)
            continue

        if cmd == "/redo":
            from ravencode.runtime.redo import redo_last

            result = await redo_last()
            console.print(result)
            continue

        if cmd == "/save" or cmd.startswith("/save "):
            path = cmd[6:].strip() if cmd.startswith("/save ") else "session.json"
            from ravencode.runtime.agent_core import ReActAgent

            agent = ReActAgent.last_agent()
            if agent is not None:
                import json

                state = agent.dump_state()
                Path(path).write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
                console.print(f"[green]Session saved to {path}[/green]")
            else:
                console.print("[red]No active session to save. Run a task first.[/red]")
            continue

        if cmd == "/load" or cmd.startswith("/load "):
            path = cmd[6:].strip() if cmd.startswith("/load ") else "session.json"
            p = Path(path)
            if not p.exists():
                console.print(f"[red]File not found: {path}[/red]")
                continue
            import json

            state = json.loads(p.read_text(encoding="utf-8"))
            agent = ReActAgent.load_state(state)
            console.print(f"[green]Session loaded from {path}. Use /ask to continue.[/green]")
            continue

        if cmd.startswith("/checkpoint"):
            parts = cmd.split(maxsplit=2)
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "save":
                desc = parts[2] if len(parts) > 2 else ""
                from ravencode.runtime.checkpoints import checkpoint_save

                result = await checkpoint_save(desc)
                console.print(result)
            elif sub == "list":
                from ravencode.runtime.checkpoints import checkpoint_list

                result = await checkpoint_list()
                console.print(result)
            elif sub == "restore" and len(parts) > 2:
                from ravencode.runtime.checkpoints import checkpoint_restore

                result = await checkpoint_restore(parts[2])
                console.print(result)
            else:
                console.print("[red]usage: /checkpoint save|list|restore <id>[/red]")
            continue

        if cmd == "/mcp":
            console.print("[yellow]Starting MCP server mode...[/yellow]")
            from ravencode.mcp.server import MCPServer

            server = MCPServer()
            await server.run()
            continue

        if cmd.startswith("/ask "):
            await run_agent(cmd[5:], AgentType.AUTONOMOUS)
            continue

        if cmd.startswith("/plan "):
            await run_agent(cmd[6:], AgentType.PLANNER)
            continue

        if cmd.startswith("/code "):
            await run_agent(cmd[6:], AgentType.CODER)
            continue

        if cmd.startswith("/debug "):
            await run_agent(cmd[7:], AgentType.DEBUGGER)
            continue

        if cmd.startswith("/agent ") and len(cmd) > 7:
            rest = cmd[7:].strip()
            name = rest.split()[0]
            task = rest[len(name) :].strip()
            agents = get_custom_agents()
            if name not in agents:
                console.print(f"[red]Unknown agent: {name}. Use /help to see available agents.[/red]")
                continue
            agent_def = agents[name]
            cfg = AgentConfig(
                max_steps=agent_def.max_steps,
                confirm_dangerous=agent_def.confirm_dangerous,
                diff_preview=agent_def.diff_preview,
                proactive_scan=agent_def.proactive_scan,
            )
            await run_streaming_agent(task or name, cfg)
            continue

        slash = cmd.split(maxsplit=1)[0]
        cmd_name = slash.lstrip("/")
        if cmd_name in custom_commands:
            args = cmd[len(slash) :].strip()
            await run_custom_command(custom_commands[cmd_name], args)
            continue

        console.print(f"[red]Unknown command: {cmd}. Type /help for available commands.[/red]")


def tui_run() -> None:
    """Entry point for the ravencode TUI."""
    asyncio.run(main_loop())


if __name__ == "__main__":
    tui_run()

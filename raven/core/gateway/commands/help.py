from __future__ import annotations

from raven.core.gateway.commands.base import CommandContext, CommandHandler


class HelpCommand(CommandHandler):
    name = "help"
    description = "Show help message"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        await gateway._send(
            ctx.event.channel,
            ctx.event.session_id,
            "Commands:\n"
            "/status - Show bot status\n"
            "/new - Start fresh conversation\n"
            "/reset - Reset session\n"
            "/task <goal> - Plan and execute a task\n"
            "/monitor list - List your monitors\n"
            "/monitor add <type> <target> - Add monitor\n"
            "/code index [path] - Index codebase\n"
            "/code search <query> - Search code\n"
            "/code review <file> - Review file\n"
            "/code start <goal> - Start coding session\n"
            "/routine list - List routines\n"
            "/routine add <action> <sched> - Add routine\n"
            "/voice tts <text> - Text-to-speech synthesis\n"
            "/voice providers - List TTS providers\n"
            "/compact - Summarize conversation\n"
            "/think <low|medium|high> - Set thinking level\n"
            "/mcp - List connected MCP servers\n"
            "/skills - List loaded skills\n"
            "/help - Show this help\n"
            "/pair <code> - Authorize with pairing code",
        )
        return True

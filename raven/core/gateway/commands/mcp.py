from __future__ import annotations

from raven.core.gateway.commands.base import CommandContext, CommandHandler


class MCPCommand(CommandHandler):
    name = "mcp"
    description = "MCP server management"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        servers = gateway.mcp.connected_count
        if servers == 0:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "No MCP servers connected.")
            return True
        lines = [f"🌐 MCP servers ({servers} connected):"]
        for info in gateway.mcp.list_servers_info():
            lines.append(f"  {info['name']}: {info['tools']} tools")
        await gateway._send(ctx.event.channel, ctx.event.session_id, "\n".join(lines))
        return True

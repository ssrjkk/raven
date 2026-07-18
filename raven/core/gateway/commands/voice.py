from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.security.sandbox_policy import check_tool_allowed, get_policy_for_channel

if TYPE_CHECKING:
    pass


class VoiceCommand(CommandHandler):
    name = "voice"
    description = "Voice/TTS commands"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        policy = get_policy_for_channel(ctx.event.channel)
        if policy is not None:
            allowed, msg = check_tool_allowed(policy, "write", ctx.event.channel)
            if not allowed:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Access denied: {msg}")
                return True

        sub = ctx.args[0].lower() if ctx.args else "help"
        sub_args = ctx.args[1:] if len(ctx.args) > 1 else []

        if sub == "tts":
            text = " ".join(sub_args) if sub_args else ""
            if not text:
                await gateway._send(ctx.event.channel, ctx.event.session_id, "Usage: /voice tts <text>")
                return True
            from raven.voice import TextToSpeech
            tts = TextToSpeech()
            try:
                output = await asyncio.get_event_loop().run_in_executor(None, tts.synthesize, text)
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"🔊 TTS saved to: {output}")
            except Exception as e:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"❌ TTS failed: {e}")

        elif sub == "providers":
            from raven.voice import TTSProvider
            providers = [p.value for p in TTSProvider]
            await gateway._send(
                ctx.event.channel, ctx.event.session_id, "🔊 TTS Providers:\n" + "\n".join(f"  • {p}" for p in providers)
            )

        else:
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                "🔊 Voice commands:\n  /voice tts <text> - Synthesize speech\n  /voice providers - List TTS providers",
            )
        return True

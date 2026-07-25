from __future__ import annotations

import asyncio
import importlib.util

import click
from rich.console import Console

from raven.core.llm import LLMRouter

console = Console()


@click.command()
@click.option("--wake/--no-wake", default=True, help="Enable/disable wake word detection")
@click.option("--stt", default="whisper", help="STT provider: whisper, google")
@click.option("--tts", default="edge", help="TTS provider: edge, gtts, system")
@click.option("--model", default=None, help="LLM model override")
@click.option("--ghost", is_flag=True, default=False, help="Offline mode — local Whisper + system TTS only")
def voice(wake: bool, stt: str, tts: str, model: str | None, ghost: bool):
    """Start a real-time voice conversation with Raven"""
    if ghost:
        from raven.core.config import apply_ghost_mode

        apply_ghost_mode()
        stt = "whisper"
        tts = "system"
    if not importlib.util.find_spec("sounddevice"):
        console.print("[red]sounddevice not installed. Install: pip install sounddevice[/red]")
        raise SystemExit(1) from None
    from raven.voice.stt import STTConfig, STTProvider
    from raven.voice.tts import TTSConfig, TTSProvider

    stt_providers = {"whisper": STTProvider.WHISPER, "google": STTProvider.GOOGLE}
    tts_providers = {"edge": TTSProvider.EDGETTS, "gtts": TTSProvider.GTTS, "system": TTSProvider.SYSTEM}
    stt_config = STTConfig(provider=stt_providers.get(stt, STTProvider.WHISPER))
    tts_config = TTSConfig(provider=tts_providers.get(tts, TTSProvider.EDGETTS))
    llm = LLMRouter()

    async def ask(text: str) -> str:
        resp = await llm.complete([{"role": "user", "content": text}], model=model)
        return resp.content

    from raven.voice.conversation import VoiceConversation

    conv = VoiceConversation(llm_ask=ask, stt_config=stt_config, tts_config=tts_config)
    try:
        asyncio.run(conv.start(wake_mode=wake))
    except KeyboardInterrupt:
        console.print("\n[yellow]Voice conversation ended[/yellow]")

"""Command bundle rendering and gateway command handler."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.models import IncomingMessage


async def _read_text(path: Path) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, path.read_text, "utf-8", "replace")


def _substitute(prompt: str, args: list[str]) -> str:
    text = prompt
    joined = " ".join(args)
    text = text.replace("$ARGUMENTS", joined).replace("$*", joined)
    for i in range(1, 10):
        value = args[i - 1] if i <= len(args) else ""
        text = text.replace(f"${i}", value)
    return text


async def render_command(bundle: Any, args: list[str]) -> str:
    """Render a command bundle: substitute args, attach refs and materials."""
    prompt = _substitute(bundle.prompt, args)
    blocks: list[str] = []
    base = bundle.source.parent if bundle.source is not None else Path.cwd()
    for ref in bundle.refs:
        path = ref if ref.is_absolute() else base / ref
        if not path.exists():
            logger.debug("[artifacts] command '{}' ref missing: {}", bundle.name, path)
            continue
        content = await _read_text(path)
        blocks.append(f"[ref: {path.name}]\n{content}")
    for name in bundle.material_names():
        path = bundle.material_path(name)
        if path is None or not path.exists():
            continue
        content = await _read_text(path)
        blocks.append(f"[material: {name}]\n{content}")
    if blocks:
        prompt = f"{prompt}\n\n" + "\n\n".join(blocks)
    return prompt


class BundleCommandHandler(CommandHandler):
    """Wraps a :class:`CommandBundle` as a gateway slash command."""

    def __init__(self, gateway: Any, bundle: Any, manager: Any):
        super().__init__(gateway)
        self._bundle = bundle
        self._manager = manager

    @property
    def name(self) -> str:
        return str(self._bundle.name)

    @property
    def description(self) -> str:
        return str(self._bundle.description)

    async def execute(self, ctx: CommandContext) -> bool:
        session_id = ctx.event.session_id or f"{ctx.event.channel}:{ctx.event.user_id}:default"
        agent_id = "default"
        try:
            session = await self.gateway.db.get_session(session_id)
            if session is not None:
                agent_id = session.agent_id
        except Exception as e:
            logger.debug("Bundle command session lookup failed: {}", e)
        root = Path(getattr(self.gateway, "_artifact_root", None) or Path.cwd())
        bundle_ctx = self._manager.context(agent_id=agent_id, channel=ctx.event.channel, cwd=root, root=root)
        bundle = self._manager.command_bundle_for(self._bundle.name, bundle_ctx)
        if bundle is None:
            await self.gateway._send(ctx.event.channel, ctx.event.session_id, "Command is not available for the current agent.")
            return True
        prompt = await render_command(bundle, ctx.args)
        event = IncomingMessage(
            channel=ctx.event.channel,
            user_id=ctx.event.user_id,
            session_id=session_id,
            text=prompt,
            metadata={"artifact_command": bundle.name},
        )
        processor = getattr(self.gateway, "_message_processor", None)
        if processor is None:
            await self.gateway._send(ctx.event.channel, ctx.event.session_id, "Agent not ready.")
            return True
        await processor.process(event, session_id)
        return True

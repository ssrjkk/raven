#!/usr/bin/env python3
"""Raven AI — Unified Launcher (RavenCode + RavenFlow)."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from pathlib import Path

with contextlib.suppress(ImportError):
    import uvloop

    uvloop.install()

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

from raven.core.logging import setup_logging


async def main() -> None:
    setup_logging()
    import argparse

    parser = argparse.ArgumentParser(description="Raven AI Unified Launcher")
    parser.add_argument("--web-port", type=int, default=18888, help="Web UI port")
    parser.add_argument("--flow-port", type=int, default=18789, help="RavenFlow gateway port")
    parser.add_argument("--no-web", action="store_true", help="Skip web UI")
    parser.add_argument("--no-flow", action="store_true", help="Skip RavenFlow gateway")
    args = parser.parse_args()

    tasks = []

    if not args.no_web:
        tasks.append(_start_web(args.web_port))

    if not args.no_flow:
        tasks.append(_start_flow(args.flow_port))

    stop_event = asyncio.Event()

    def _shutdown() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _shutdown)

    logger.info("Raven AI starting...")
    logger.info("Web UI:   http://localhost:{}", args.web_port)
    logger.info("RavenFlow: http://localhost:{}", args.flow_port)
    logger.info("Press Ctrl+C to stop.")

    _done, pending = await asyncio.wait(
        [asyncio.create_task(t) for t in tasks] + [asyncio.create_task(stop_event.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for p in pending:
        p.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    logger.info("Raven AI stopped.")


async def _start_web(port: int) -> None:
    try:
        from raven.cli.gateway_runner import _run_gateway, create_gateway

        gateway = create_gateway()
        await _run_gateway(gateway, port)
    except ImportError as exc:
        logger.warning("Web UI unavailable: {}", exc)


async def _start_flow(port: int) -> None:
    try:
        from raven.gateway.daemon import RavenFlowDaemon
        daemon = RavenFlowDaemon(port=port)
        await daemon.start()
    except ImportError as exc:
        logger.warning("RavenFlow unavailable: {}", exc)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except ModuleNotFoundError as exc:
        logger.error("Missing dependency: {}", exc)
        sys.exit(1)

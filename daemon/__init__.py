from __future__ import annotations

import asyncio


def _ensure_raven_env() -> None:
    from raven.core.config_store import config_store

    config_store.load()
    config_store.apply_to_env()


def run_gateway():
    _ensure_raven_env()

    from raven.cli.main import _run_gateway, create_gateway
    from raven.core.config import settings

    gateway = create_gateway()
    asyncio.run(_run_gateway(gateway, settings.web_port))

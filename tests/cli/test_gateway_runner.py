from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from raven.cli.gateway_runner import _server_config


def test_access_log_is_disabled() -> None:
    """The access log prints the raw request line, and SSE/WebSocket auth travels in ?token=."""
    config = _server_config(FastAPI(), "127.0.0.1", 8000)
    assert isinstance(config, uvicorn.Config)
    assert config.access_log is False
    assert config.ws == "auto"
    assert config.host == "127.0.0.1"
    assert config.port == 8000

from __future__ import annotations

import contextlib
import sys
from typing import Any


def _pin(streams: tuple[Any, ...]) -> None:
    for stream in streams:
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")


def use_utf8_stdio() -> None:
    """Pin the stdio transport to UTF-8, the only encoding the MCP spec allows on the wire.

    Left alone, `sys.stdin`/`sys.stdout` inherit this machine's ANSI code page (cp1251 on a
    Russian Windows, ascii under a POSIX C locale), so a host's UTF-8 frames arrive decoded into
    the wrong string and any result the code page cannot encode raises UnicodeEncodeError inside
    `_send_response`, which ended the session with a traceback.
    """
    _pin((sys.stdin, sys.stdout, sys.stderr))


def use_utf8_console() -> None:
    """Pin human-facing output to UTF-8 so no glyph a console cannot encode kills the process.

    rich writes through `sys.stdout`'s encoder, so on a cp1251 console printing a box-drawing
    character or a CJK title raises UnicodeEncodeError out of `_check_buffer` and the command
    exits 1 with no output at all.
    """
    _pin((sys.stdout, sys.stderr))

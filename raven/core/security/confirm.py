from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

# A confirmer is a capability, not a callback detail: an agent built without one cannot ask, and
# EXEC_ASK=always must therefore refuse rather than run. Terminals use this implementation; channels
# supply their own (the gateway's message processor does).


async def terminal_confirm(tool_name: str, arguments: dict[str, Any]) -> bool:
    """Ask on the controlling terminal. A run with no terminal denies, which is the safe answer."""
    summary = ", ".join(f"{k}={str(v)[:60]}" for k, v in list(arguments.items())[:6])
    try:
        answer = await asyncio.to_thread(input, f"Allow {tool_name}({summary})? [y/N] ")
    except (EOFError, OSError) as exc:
        logger.info("Confirmation unavailable ({}), denying {}", type(exc).__name__, tool_name)
        return False
    return answer.strip().lower() in {"y", "yes", "да", "д"}

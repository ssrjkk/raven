"""E2E: ravencode agent fixes a buggy file via the real LLM."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJ = Path(os.environ.get("TEMP", os.environ.get("TMP", "."))) / "ravencode-e2e"


async def main() -> None:
    from ravencode.runtime.workspace import set_workspace_root

    set_workspace_root(PROJ)

    from ravencode.runtime.agent_core import AgentConfig, ReActAgent

    calc = PROJ / "calc.py"
    print("before:", calc.read_text().strip())

    agent = ReActAgent(AgentConfig(max_steps=6, confirm_dangerous=False))
    result = await agent.run(
        "In calc.py the add() function subtracts instead of adding. "
        "Fix it so add(a, b) returns a + b. Use the edit tool."
    )
    text = result if isinstance(result, str) else str(result)
    sys.stdout.buffer.write(("agent output tail: " + text[-300:] + "\n").encode("utf-8", "replace"))
    print("after:", calc.read_text().strip())

    ok = "return a + b" in calc.read_text()
    print("FIXED" if ok else "NOT FIXED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())

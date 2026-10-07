from __future__ import annotations

import argparse
import asyncio

from raven.core.mcp.server import run_mcp_server
from ravencode.runtime.workspace import set_workspace_root


def main() -> None:
    parser = argparse.ArgumentParser(prog="raven-mcp", description="Raven MCP server (stdio)")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Root directory tools may access (default: current directory)",
    )
    args = parser.parse_args()
    set_workspace_root(args.workspace)
    asyncio.run(run_mcp_server())


if __name__ == "__main__":
    main()

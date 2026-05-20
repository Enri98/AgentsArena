"""Entry point: python -m arena.mcp [--stdio | --http [--host H] [--port P]]."""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m arena.mcp",
        description="Arena MCP server — exposes arena.sdk tools to MCP clients.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--stdio",
        action="store_true",
        default=False,
        help="Run over stdio (default; required for Claude Desktop).",
    )
    mode.add_argument(
        "--http",
        action="store_true",
        default=False,
        help="Run over HTTP/SSE.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind when using --http (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="Port to bind when using --http (default: 9000).",
    )

    args = parser.parse_args()

    if args.http:
        host: str = args.host
        if host not in ("127.0.0.1", "localhost"):
            print(
                "WARNING: MCP HTTP/SSE has no authentication. "
                "Only expose on trusted networks. v1 scope.",
                file=sys.stderr,
            )
        from arena.mcp.server import run_http

        run_http(host=host, port=args.port)
    else:
        # Default: stdio
        from arena.mcp.server import run_stdio

        run_stdio()


if __name__ == "__main__":
    main()

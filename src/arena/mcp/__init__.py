"""arena.mcp — MCP server layer exposing arena.sdk to Claude Desktop and other MCP clients."""
from __future__ import annotations

from arena.mcp.server import build_server, run_http, run_stdio
from arena.mcp.session_registry import SessionRegistry

__all__ = [
    "build_server",
    "run_stdio",
    "run_http",
    "SessionRegistry",
]

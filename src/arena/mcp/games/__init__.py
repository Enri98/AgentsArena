"""MCP per-game adapter modules.

Importing this package triggers each per-game submodule's top-level
:func:`arena.mcp._adapters.register_mcp_adapter` call.
"""

from __future__ import annotations

from arena.mcp.games import connect4 as _connect4  # noqa: F401
from arena.mcp.games import nim as _nim  # noqa: F401
from arena.mcp.games import tictactoe as _tictactoe  # noqa: F401

__all__: tuple[str, ...] = ()

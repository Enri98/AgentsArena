"""JSON Schema dicts for each game's action input, used by MCP tool descriptions.

The per-game action schemas now live with each game's MCP adapter module
under ``arena/mcp/games/<name>.py`` and are looked up through the
:data:`arena.mcp._adapters.MCP_GAME_ADAPTERS` registry. The module-level
re-exports here are kept for backwards compatibility with external callers
that may have imported the schema constants directly.
"""
from __future__ import annotations

from collections.abc import Sequence

# Importing the games package fires each per-game adapter registration.
from arena.mcp import games as _games  # noqa: F401
from arena.mcp._adapters import MCP_GAME_ADAPTERS
from arena.mcp.games.connect4 import CONNECT4_ACTION_SCHEMA
from arena.mcp.games.nim import NIM_ACTION_SCHEMA
from arena.mcp.games.tictactoe import TICTACTOE_ACTION_SCHEMA


def game_action_schema(game_id: str) -> dict[str, object]:
    """Return the JSON Schema for a game's action, or a generic object schema."""

    adapter = MCP_GAME_ADAPTERS.get(game_id)
    if adapter is None:
        return {"type": "object"}
    return adapter.action_schema


__all__: Sequence[str] = [
    "CONNECT4_ACTION_SCHEMA",
    "TICTACTOE_ACTION_SCHEMA",
    "NIM_ACTION_SCHEMA",
    "game_action_schema",
]

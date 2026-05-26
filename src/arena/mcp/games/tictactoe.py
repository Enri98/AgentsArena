"""MCP adapter registration for Tic-Tac-Toe."""

from __future__ import annotations

from arena.games.tictactoe.definition import TICTACTOE_GAME_ID
from arena.mcp._adapters import McpGameAdapter, register_mcp_adapter

TICTACTOE_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "row": {"type": "integer", "minimum": 0},
        "column": {"type": "integer", "minimum": 0},
    },
    "required": ["row", "column"],
}


register_mcp_adapter(
    McpGameAdapter(
        game_id=TICTACTOE_GAME_ID,
        action_schema=TICTACTOE_ACTION_SCHEMA,
    )
)


__all__: tuple[str, ...] = ("TICTACTOE_ACTION_SCHEMA",)

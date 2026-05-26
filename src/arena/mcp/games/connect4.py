"""MCP adapter registration for Connect 4."""

from __future__ import annotations

from arena.games.connect4.definition import CONNECT4_GAME_ID
from arena.mcp._adapters import McpGameAdapter, register_mcp_adapter

CONNECT4_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "column": {"type": "integer", "minimum": 0},
    },
    "required": ["column"],
}


register_mcp_adapter(
    McpGameAdapter(
        game_id=CONNECT4_GAME_ID,
        action_schema=CONNECT4_ACTION_SCHEMA,
    )
)


__all__: tuple[str, ...] = ("CONNECT4_ACTION_SCHEMA",)

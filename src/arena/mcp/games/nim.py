"""MCP adapter registration for Nim."""

from __future__ import annotations

from arena.games.nim.definition import NIM_GAME_ID
from arena.mcp._adapters import McpGameAdapter, register_mcp_adapter

NIM_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "pile_index": {"type": "integer", "minimum": 0},
        "count": {"type": "integer", "minimum": 1},
    },
    "required": ["pile_index", "count"],
}


register_mcp_adapter(
    McpGameAdapter(
        game_id=NIM_GAME_ID,
        action_schema=NIM_ACTION_SCHEMA,
    )
)


__all__: tuple[str, ...] = ("NIM_ACTION_SCHEMA",)

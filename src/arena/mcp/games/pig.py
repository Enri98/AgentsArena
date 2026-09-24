"""MCP adapter registration for Pig."""

from __future__ import annotations

from arena.games.pig.definition import PIG_GAME_ID
from arena.mcp._adapters import McpGameAdapter, register_mcp_adapter

PIG_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "choice": {
            "type": "string",
            "enum": ["roll", "hold"],
            "description": (
                "'roll' to roll the die again (a 1 loses this turn's points), "
                "'hold' to bank your turn total. A turn must start with a roll."
            ),
        },
    },
    "required": ["choice"],
}


register_mcp_adapter(
    McpGameAdapter(
        game_id=PIG_GAME_ID,
        action_schema=PIG_ACTION_SCHEMA,
    )
)


__all__: tuple[str, ...] = ("PIG_ACTION_SCHEMA",)

"""MCP adapter registration for Liar's Dice."""

from __future__ import annotations

from arena.games.liarsdice.definition import LIARSDICE_GAME_ID
from arena.mcp._adapters import McpGameAdapter, register_mcp_adapter

LIARSDICE_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "oneOf": [
        {
            "type": "object",
            "description": (
                "Claim that at least `quantity` dice across BOTH hands show `face`. "
                "Must raise the standing bid: more dice, or as many of a higher face."
            ),
            "properties": {
                "type": {"const": "bid"},
                "quantity": {"type": "integer", "minimum": 1},
                "face": {"type": "integer", "minimum": 1},
            },
            "required": ["type", "quantity", "face"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "description": (
                "Challenge the standing bid. Both hands are revealed; if the bid holds "
                "you lose a die, otherwise the bidder does."
            ),
            "properties": {"type": {"const": "call"}},
            "required": ["type"],
            "additionalProperties": False,
        },
    ],
}


register_mcp_adapter(
    McpGameAdapter(
        game_id=LIARSDICE_GAME_ID,
        action_schema=LIARSDICE_ACTION_SCHEMA,
    )
)


__all__: tuple[str, ...] = ("LIARSDICE_ACTION_SCHEMA",)

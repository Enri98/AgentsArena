"""MCP adapter registration for Rock-Paper-Scissors."""

from __future__ import annotations

from arena.games.rps.definition import RPS_GAME_ID
from arena.mcp._adapters import McpGameAdapter, register_mcp_adapter

RPS_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "shape": {
            "type": "string",
            "enum": ["rock", "paper", "scissors"],
            "description": (
                "Your throw for this round. Both seats throw at once: rock beats "
                "scissors, scissors beats paper, paper beats rock. make_move returns "
                "once the other seat has thrown too."
            ),
        },
    },
    "required": ["shape"],
    "additionalProperties": False,
}


register_mcp_adapter(
    McpGameAdapter(
        game_id=RPS_GAME_ID,
        action_schema=RPS_ACTION_SCHEMA,
    )
)


__all__: tuple[str, ...] = ("RPS_ACTION_SCHEMA",)

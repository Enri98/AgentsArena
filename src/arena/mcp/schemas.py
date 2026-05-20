"""JSON Schema dicts for each game's action input, used by MCP tool descriptions."""
from __future__ import annotations

from collections.abc import Sequence

# Connect 4: drop a disc into a column
CONNECT4_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "column": {"type": "integer", "minimum": 0},
    },
    "required": ["column"],
}

# Tic-Tac-Toe: place a mark at (row, column)
TICTACTOE_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "row": {"type": "integer", "minimum": 0},
        "column": {"type": "integer", "minimum": 0},
    },
    "required": ["row", "column"],
}

# Nim: take *count* objects from *pile_index*
NIM_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "pile_index": {"type": "integer", "minimum": 0},
        "count": {"type": "integer", "minimum": 1},
    },
    "required": ["pile_index", "count"],
}

_GAME_SCHEMAS: dict[str, dict[str, object]] = {
    "connect4": CONNECT4_ACTION_SCHEMA,
    "tictactoe": TICTACTOE_ACTION_SCHEMA,
    "nim": NIM_ACTION_SCHEMA,
}


def game_action_schema(game_id: str) -> dict[str, object]:
    """Return the JSON Schema for a game's action, or a generic object schema."""
    return _GAME_SCHEMAS.get(game_id, {"type": "object"})


__all__: Sequence[str] = [
    "CONNECT4_ACTION_SCHEMA",
    "TICTACTOE_ACTION_SCHEMA",
    "NIM_ACTION_SCHEMA",
    "game_action_schema",
]
